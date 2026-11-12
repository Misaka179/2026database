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

    def admin(self,name,account):
        return {'kind':'admin','id':self.s.create_admin(self.super,name,account,'AdminPassword123!')['admin_id']}

    def setUp(self):
        SemesterTests.setUp(self)
        self.consult=[b for b in self.s.businesses(self.super) if b['code']=='CONSULT'][0]['business_id']
        self.art=[b for b in self.s.businesses(self.super) if b['code']=='ART'][0]['business_id']
        self.lead=self.admin('一分队负责人','leader-one')
        self.s.appoint_business_leader(self.super,self.consult,1,self.lead['id'],'任命一分队负责人')
        self.lead=self.s.login('admin','leader-one','AdminPassword123!')
        self.other=self.admin('空闲管理员','spare-admin')

    def test_scope_visibility_and_default_deny(self):
        self.term()
        d=self.s.leader_workspace(self.lead)
        self.assertEqual(len(d['slots']),5)
        self.assertEqual({r['slot_id'] for r in d['schedules']},{self.mon})
        self.assertNotIn('password_hash',str(d))
        self.assertEqual(self.s.collections(self.lead),[])
        with self.assertRaises(DomainError):self.s.create_collection(self.lead,self.consult,'分队越权','2026-09-07','2026-09-13',[self.student['id']],[{'title':'任务','min_minutes':30,'max_minutes':60}])
        with self.assertRaises(DomainError) as e:self.s.configure_slot(self.lead,self.mon,self.other['id'],20)
        self.assertEqual(e.exception.status,403)
        self.s.configure_slot(self.super,self.mon,self.other['id'],20)
        with self.assertRaises(DomainError):self.s.configure_slot(self.lead,self.tue,self.other['id'],20)
        for label,run in (('set_rule',lambda:self.s.set_rule(self.lead,'ABSENT',1,'不得修改')),
                    ('set_student_credit',lambda:self.s.set_student_credit(self.lead,self.student['id'],1,1,'不得修改')),
                    ('create_admin',lambda:self.s.create_admin(self.lead,'伪造','bad','BadPassword123!')),
                    ('appoint_other_business',lambda:self.s.appoint_business_leader(self.lead,self.art,2,self.other['id'],'不得任命'))):
            with self.subTest(action=label):
                with self.assertRaises(DomainError) as e:run()
                self.assertEqual(e.exception.status,403)
        self.s.reset_password(self.lead,'student',self.student['id'],'ResetPassword123!','队员申请')
        with self.assertRaises(DomainError):self.s.reset_password(self.lead,'admin',self.super['id'],'ResetPassword123!','越权')
        replacement=self.admin('接手一分队','leader-replacement')
        self.s.appoint_business_leader(self.super,self.consult,1,replacement['id'],'负责人交接')
        self.assertEqual(self.s.leader_workspace(self.lead)['slots'],[])
        with self.assertRaises(DomainError):self.s.configure_slot(self.lead,self.mon,None,20)

    def test_one_admin_one_scope_and_business_candidates(self):
        admin2=self.admin('二分队负责人','leader-two')
        self.s.appoint_business_leader(self.super,self.consult,2,admin2['id'],'二分队')
        self.assertEqual(len(self.s.leader_workspace(admin2)['slots']),5)
        with self.assertRaises(DomainError):
            self.s.appoint_leader(self.super,3,admin2['id'],'兼任第三分队')
        with self.assertRaises(DomainError):
            self.s.configure_business_owner(self.super,self.art,admin2['id'],'兼任业务负责人')
        busy=self.rows('SELECT admin_id FROM leader_scope WHERE admin_id IS NOT NULL')
        candidates={a['admin_id'] for a in self.s.business_admins(self.super,self.consult)}
        self.assertFalse(candidates & {r['admin_id'] for r in busy})
        self.assertIn(self.other['id'],candidates)

    def test_business_owner_business_wide_rights(self):
        with self.db.transaction(True) as c:
            c.execute('UPDATE service_slot SET manager_admin_id=NULL WHERE manager_admin_id=%s',(self.normal['id'],))
        self.s.configure_business_owner(self.super,self.consult,self.normal['id'],'设业务负责人')
        consult_row=[b for b in self.s.businesses(self.normal) if b['business_id']==self.consult][0]
        self.assertTrue(consult_row['can_manage'])
        self.assertTrue(consult_row['can_collect_all'])
        self.assertIn(self.student['id'],{r['student_id'] for r in self.s.students(self.normal)})
        managed=self.rows('SELECT manager_admin_id FROM service_slot WHERE slot_id=%s',(self.tue,))[0]['manager_admin_id']
        self.s.configure_slot(self.normal,self.tue,managed,18)
        self.assertEqual(self.rows('SELECT need_num FROM service_slot WHERE slot_id=%s',(self.tue,))[0]['need_num'],18)
        self.assertEqual(self.rows('SELECT manager_admin_id FROM service_slot WHERE slot_id=%s',(self.tue,))[0]['manager_admin_id'],managed)
        self.assertNotIn(self.normal['id'],{a['admin_id'] for a in self.s.business_admins(self.normal,self.consult)})
        self.s.appoint_business_leader(self.normal,self.consult,2,self.other['id'],'二分队负责人')
        self.assertEqual(self.rows('SELECT admin_id FROM leader_scope WHERE business_id=%s AND weekday=2 AND active=1',(self.consult,))[0]['admin_id'],
                         self.other['id'])
        with self.assertRaises(DomainError):self.s.appoint_business_leader(self.normal,self.art,2,self.other['id'],'越权任命')
        with self.assertRaises(DomainError):self.s.configure_business_owner(self.normal,self.consult,self.normal['id'],'自封')
        self.s.configure_business_owner(self.super,self.consult,None,'撤销业务负责人')
        with self.assertRaises(DomainError) as e:self.s.configure_slot(self.normal,self.tue,managed,20)
        self.assertEqual(e.exception.status,403)

    def test_withdrawal_single_review_and_no_leader_fallback(self):
        self.term()
        sid=self.s.create_student(self.super,'withdraw-clean','退队测试','WithdrawPassword123!')['student_id']
        self.s.set_memberships(self.super,sid,[self.mon])
        stu=self.s.login('student',sid,'WithdrawPassword123!')
        wid=self.s.apply_withdrawal(stu,'退出申请')['withdrawal_id']
        self.assertTrue(next(r for r in self.s.list_applications(self.super,'withdrawal') if r['withdrawal_id']==wid)['can_review'])
        with self.assertRaises(DomainError):self.s.first_review_withdrawal(self.normal,wid,True,'越权')
        self.assertEqual(self.s.first_review_withdrawal(self.lead,wid,True,'核对完成')['status'],'APPROVED')
        self.assertEqual(self.rows('SELECT status FROM student WHERE student_id=%s',(sid,))[0]['status'],'QUIT')
        self.assertTrue(self.s.first_review_withdrawal(self.lead,wid,True,'核对完成')['replayed'])
        wid2=self.s.apply_withdrawal(self.student,'历史多范围直接终审')['withdrawal_id']
        self.assertEqual(self.rows('SELECT status FROM withdrawal_leader_review WHERE withdrawal_id=%s',(wid2,))[0]['status'],'NOT_REQUIRED')
        self.s.approve_withdrawal(self.super,wid2,True)

    def test_legacy_conflict_goes_to_global_super_and_is_not_expanded(self):
        self.s.set_memberships(self.super,self.student['id'],[self.mon,self.tue])
        with self.assertRaises(DomainError):self.s.set_memberships(self.super,self.student['id'],[self.mon,self.tue,self.sat])
        wid=self.s.apply_withdrawal(self.student,'历史多分队直接终审')['withdrawal_id']
        self.assertEqual(self.s.leader_workspace(self.lead)['withdrawal'],())
        self.s.approve_withdrawal(self.super,wid,True)

    def test_daily_report_weekly_increase_correction_and_export(self):
        self.term()
        self.now=datetime(2026,9,7,23)
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
        self.now=datetime(2026,9,22)
        self.assertGreaterEqual(self.s.run_leader_reports()['created'],1)

    def test_admin_account_password_is_independent(self):
        sid=self.s.create_student(self.super,'independent-student','独立队员','StudentPassword123!')['student_id']
        self.s.set_memberships(self.super,sid,[self.mon])
        admin=self.admin('独立管理员','independent-admin')
        self.s.reset_password(self.super,'student',sid,'StudentPassword456!','本人申请')
        self.s.login('student',sid,'StudentPassword456!')
        self.assertEqual(self.s.login('admin','independent-admin','AdminPassword123!')['id'],admin['id'])
        with self.assertRaises(DomainError):
            self.s.reset_password(self.lead,'admin',admin['id'],'AdminPassword456!','普通管理员不能重置管理员密码')

    def test_migration_idempotence_http_and_rollback(self):
        before=self.rows('SELECT * FROM leader_scope')
        migrate(self.settings);migrate(self.settings)
        self.assertEqual(before,self.rows('SELECT * FROM leader_scope'))
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.s.appoint_leader(self.super,2,self.other['id'],'回滚')
        self.assertEqual(before,self.rows('SELECT * FROM leader_scope'))
        app.dependency_overrides[get_service]=lambda:self.s
        try:
            with TestClient(app) as client:
                headers={'Authorization':'Bearer '+issue_token(self.lead)}
                self.assertEqual(client.get('/leader-workspace',headers=headers).status_code,200)
                self.assertEqual(client.get('/auth/me',headers=headers).status_code,200)
                self.assertEqual(client.get('/slots',headers=headers).status_code,200)
                for path in ('/admins','/operation-logs'):
                    self.assertEqual(client.get(path,headers=headers).status_code,403,path)
                self.assertEqual(client.get('/inbox',headers=headers).status_code,200)
        finally:app.dependency_overrides.clear()


if __name__=='__main__':unittest.main()
