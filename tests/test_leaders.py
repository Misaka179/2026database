import unittest
from datetime import datetime
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from fastapi.testclient import TestClient
from app.api import app,get_service
from app.security import issue_token
from app.service import DomainError
from app.leaders import migrate
from app.hours_export import export_hours
from test_semester import SemesterTests


class LeaderTests(unittest.TestCase):
    rows=SemesterTests.rows
    term=SemesterTests.term

    def setUp(self):
        SemesterTests.setUp(self)
        with self.db.transaction(True) as c:
            c.execute('DELETE FROM slot_member WHERE student_id=%s AND slot_id<>%s',(self.student['id'],self.mon))
        self.s.create_student(self.super,'leader-person','负责人候选','LeadPassword123!')
        self.s.create_student(self.super,'leader-other','其他负责人','LeadPassword123!')
        self.s.appoint_leader(self.super,1,'leader-person','任命一分队负责人')
        self.lead=self.s.login('admin','lead-leader-person','LeadPassword123!')

    def test_nomination_scope_and_default_deny(self):
        self.term()
        d=self.s.leader_workspace(self.lead)
        self.assertEqual(len(d['slots']),5)
        self.assertEqual({r['slot_id'] for r in d['schedules']},{self.mon})
        self.assertNotIn('password_hash',str(d))
        self.s.configure_slot(self.lead,self.mon,self.normal['id'],20)
        promoted=self.s.promote_student(self.lead,self.student['id'],'本队时段管理员',[self.mon])
        self.s.configure_slot(self.lead,self.mon,promoted['admin_id'],20)
        with self.assertRaises(DomainError):self.s.promote_student(self.lead,'leader-other','跨范围任命',[self.mon])
        with self.assertRaises(DomainError):self.s.configure_slot(self.lead,self.tue,self.normal['id'],20)
        for run in (lambda:self.s.set_rule(self.lead,'ABSENT',1,'不得修改'),
                    lambda:self.s.set_student_credit(self.lead,self.student['id'],1,1,'不得修改'),
                    lambda:self.s.students(self.lead),lambda:self.s.list_schedules(self.lead),
                    lambda:self.s.create_admin(self.lead,'伪造','bad','BadPassword123!'),
                    lambda:self.s.appoint_leader(self.lead,2,'leader-person','不得任命')):
            with self.assertRaises(DomainError) as e:run()
            self.assertEqual(e.exception.status,403)
        self.s.reset_password(self.lead,'student',self.student['id'],'ResetPassword123!','队员申请')
        with self.assertRaises(DomainError):self.s.reset_password(self.lead,'admin',self.super['id'],'ResetPassword123!','越权')
        with self.assertRaises(DomainError):self.s.reset_password(self.lead,'student','leader-other','ResetPassword123!','越权')
        self.s.appoint_leader(self.super,1,'leader-other','负责人交接')
        self.assertEqual(self.s.leader_workspace(self.lead)['slots'],[])
        with self.assertRaises(DomainError):self.s.configure_slot(self.lead,self.mon,None,20)

    def test_art_whole_week_and_single_team_validation(self):
        self.s.appoint_leader(self.super,8,'leader-other','美育任命')
        art=self.s.login('admin','lead-leader-other','LeadPassword123!')
        slots=self.s.leader_workspace(art)['slots']
        self.assertEqual(len(slots),28)
        self.assertEqual({r['weekday'] for r in slots},set(range(1,8)))
        with self.assertRaises(DomainError):self.s.set_memberships(self.super,self.student['id'],[self.mon,self.tue])
        # Keep the normal admin identity separate and its password synchronized.
        ordinary=self.s.promote_student(self.super,'leader-person','时段管理',[])
        self.assertNotEqual(ordinary['admin_id'],self.lead['id'])
        self.s.reset_password(self.super,'student','leader-person','UpdatedPassword123!','修改密码')
        self.assertEqual(self.s.login('admin','lead-leader-person','UpdatedPassword123!'),self.lead)
        self.assertEqual(self.s.login('admin','leader-person','UpdatedPassword123!')['id'],ordinary['admin_id'])

    def test_withdrawal_initial_final_and_no_leader_fallback(self):
        self.term()
        wid=self.s.apply_withdrawal(self.student,'退出申请')['withdrawal_id']
        with self.assertRaises(DomainError):self.s.approve_withdrawal(self.super,wid,True)
        with self.assertRaises(DomainError):self.s.first_review_withdrawal(self.normal,wid,True,'越权')
        self.s.first_review_withdrawal(self.lead,wid,True,'核对完成')
        self.assertEqual(self.rows('SELECT status FROM student WHERE student_id=%s',(self.student['id'],))[0]['status'],'ACTIVE')
        self.assertTrue(self.s.first_review_withdrawal(self.lead,wid,True,'核对完成')['replayed'])
        self.s.approve_withdrawal(self.super,wid,True)
        self.assertEqual(self.rows('SELECT status FROM student WHERE student_id=%s',(self.student['id'],))[0]['status'],'QUIT')

    def test_legacy_conflict_goes_to_global_super_and_is_not_expanded(self):
        with self.db.transaction(True) as c:
            c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(self.student['id'],self.tue))
        self.s.set_memberships(self.super,self.student['id'],[self.mon,self.tue])
        with self.assertRaises(DomainError):self.s.set_memberships(self.super,self.student['id'],[self.mon,self.tue,self.sat])
        wid=self.s.apply_withdrawal(self.student,'历史多分队直接终审')['withdrawal_id']
        self.assertEqual(self.s.leader_workspace(self.lead)['withdrawal'],())
        self.s.approve_withdrawal(self.super,wid,True)

    def test_daily_report_weekly_increase_correction_and_export(self):
        self.term()
        self.now=datetime(2026,9,7,23)
        row=self.s.leader_workspace(self.lead)['schedules'][-1]
        # Pick the first service day rather than depending on IDs.
        row=next(r for r in self.s.leader_workspace(self.lead)['schedules'] if str(r['schedule_date'])=='2026-09-07')
        self.s.increase_fixed_hours(self.normal,row['schedule_id'],150,120,'额外工作')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        notices=self.s.inbox(self.lead)['items']
        self.assertTrue(any(r['title']=='时段管理员上调服务时长' for r in notices))
        self.assertEqual(self.s.run_leader_reports()['created'],1)
        self.assertEqual(self.s.run_leader_reports()['created'],0)
        rid=self.s.leader_workspace(self.lead)['reports'][0]['report_id']
        report=self.s.leader_report(self.lead,rid)['payload']
        self.assertEqual((report['expected_minutes'],report['recognized_minutes']),(150,0))
        self.s.record_attendance(self.lead,row['schedule_id'],'ABSENT','缺勤')
        self.s.correct_attendance(self.lead,row['schedule_id'],'NORMAL','考勤核实',1)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],120)
        self.assertEqual(self.s.leader_report(self.lead,rid)['payload'],report)
        tid=self.s.leader_workspace(self.lead)['semesters'][0]['semester_id']
        book=load_workbook(BytesIO(export_hours(self.s,self.lead,tid)))
        self.assertEqual(len(book.worksheets),3)
        text=str([[list(r) for r in ws.values] for ws in book])
        self.assertNotIn('二分队',text)
        self.now=datetime(2026,9,22)
        self.assertEqual(self.s.run_leader_reports()['created'],2)

    def test_migration_idempotence_http_and_rollback(self):
        before=self.rows('SELECT * FROM leader_scope')
        migrate(self.settings);migrate(self.settings)
        self.assertEqual(before,self.rows('SELECT * FROM leader_scope'))
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.s.appoint_leader(self.super,2,'leader-other','回滚')
        self.assertEqual(before,self.rows('SELECT * FROM leader_scope'))
        app.dependency_overrides[get_service]=lambda:self.s
        try:
            with TestClient(app) as client:
                headers={'Authorization':'Bearer '+issue_token(self.lead)}
                self.assertEqual(client.get('/leader-workspace',headers=headers).status_code,200)
                self.assertEqual(client.get('/auth/me',headers=headers).status_code,200)
                for path in ('/slots','/students','/schedules','/businesses','/hour-collections','/admins','/operation-logs'):
                    self.assertEqual(client.get(path,headers=headers).status_code,403,path)
                self.assertEqual(client.get('/inbox',headers=headers).status_code,200)
        finally:app.dependency_overrides.clear()


if __name__=='__main__':unittest.main()
