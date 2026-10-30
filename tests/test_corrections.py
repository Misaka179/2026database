"""Real MySQL regressions for catch-up credit, attendance revisions and reversals."""
import unittest
from datetime import datetime, date
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_semester as fixtures
from app.service import DomainError


class CorrectionTests(unittest.TestCase):
    setUp = fixtures.SemesterTests.setUp
    term = fixtures.SemesterTests.term
    rows = fixtures.SemesterTests.rows
    schedules = fixtures.SemesterTests.schedules
    on = fixtures.SemesterTests.on

    def absent(self):
        self.term()
        sid=self.on('2026-09-07')
        self.now=datetime(2026,9,7,12)
        self.s.record_attendance(self.normal,sid,'ABSENT')
        return sid

    def test_august_start_catches_up_three_weeks_even_without_configuration(self):
        self.now=datetime(2026,9,27,21)
        with self.db.transaction(True) as c:
            c.execute('UPDATE service_slot SET manager_admin_id=NULL,need_num=NULL WHERE weekday IS NOT NULL')
        tid=self.term('2026-08-31',15)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],1260)
        self.assertEqual(len(self.schedules('COMPLETED')),9)
        self.assertEqual({r['week_no'] for r in self.schedules('COMPLETED')},{1,2,3})
        self.assertEqual(self.s.run_weekly_settlement()['settled'],0)
        self.assertEqual(self.s.sync_calendar(self.super,tid)['created'],0)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],1260)

    def test_backfill_keeps_absence_and_never_credits_holidays(self):
        self.now=datetime(2026,8,30)
        self.term('2026-08-31',5)
        sid=self.on('2026-08-31')
        self.now=datetime(2026,8,31,12)
        self.s.record_attendance(self.normal,sid,'ABSENT')
        self.now=datetime(2026,9,27,21)
        self.s.run_weekly_settlement()
        self.assertEqual(self.s.hours(self.student)['total_minutes'],1140)
        self.assertEqual(self.s.credit(self.student)['credit_score'],2)
        self.assertFalse(any(date(2026,9,25)<=r['schedule_date']<=date(2026,9,27) for r in self.schedules()))

    def test_wrong_absence_is_reversed_once_and_hours_restored(self):
        sid=self.absent()
        original=self.s.credit(self.student)['logs'][0]
        result=self.s.correct_attendance(self.normal,sid,'NORMAL','缺勤登记错误',1)
        self.assertEqual(result['refunded_score'],3)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],120)
        self.assertTrue(self.s.correct_attendance(self.normal,sid,'NORMAL','重复提交',1)['replayed'])
        logs=self.s.credit(self.student)['logs']
        self.assertEqual(len(logs),2)
        self.assertEqual(logs[0],original)
        self.assertEqual(logs[1]['entry_type'],'REVERSAL')
        self.assertEqual(logs[1]['reverses_log_id'],original['credit_log_id'])
        self.assertEqual(self.rows('SELECT status FROM violation')[0]['status'],'REVOKED')

    def test_repeated_reclassification_retains_all_original_penalties(self):
        sid=self.absent()
        self.s.correct_attendance(self.normal,sid,'LATE','实际为迟到',1)
        self.assertEqual(self.s.credit(self.student)['credit_score'],4)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],120)
        self.s.correct_attendance(self.super,sid,'NORMAL','核实准时到岗',2)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.s.correct_attendance(self.super,sid,'ABSENT','重新核实缺勤',3)
        self.s.correct_attendance(self.super,sid,'LEAVE','事后确认请假',4)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.assertEqual(len(self.rows('SELECT * FROM violation')),3)
        self.assertTrue(all(r['status']=='REVOKED' for r in self.rows('SELECT * FROM violation')))

    def test_floor_refund_uses_actual_deduction_and_restores_only_credit_cancellations(self):
        self.term()
        mon,tue,sat=self.on('2026-09-07'),self.on('2026-09-08'),self.on('2026-09-12')
        self.s.cancel_schedule(self.normal,sat,'手动例外取消')
        self.now=datetime(2026,9,7,12)
        self.s.record_attendance(self.normal,mon,'ABSENT')
        self.now=datetime(2026,9,8,17)
        self.s.record_attendance(self.normal,tue,'ABSENT')
        self.assertEqual(self.s.credit(self.student)['status'],'DISABLED')
        result=self.s.correct_attendance(self.normal,tue,'NORMAL','第二次误记',1)
        self.assertEqual(result['refunded_score'],2)
        self.assertEqual(self.s.credit(self.student)['credit_score'],2)
        self.assertEqual(self.s.credit(self.student)['status'],'ACTIVE')
        self.assertTrue(self.schedules())
        self.assertFalse(any(r['schedule_date']==date(2026,9,12) for r in self.schedules()))
        self.s.correct_attendance(self.normal,mon,'NORMAL','第一次误记',1)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)

    def test_quit_and_manually_disabled_people_are_not_reactivated(self):
        sid=self.absent()
        wid=self.s.apply_withdrawal(self.student,'退出')['withdrawal_id']
        self.s.approve_withdrawal(self.super,wid,True)
        self.s.correct_attendance(self.normal,sid,'NORMAL','退队前缺勤误记',1)
        self.assertEqual(self.s.credit(self.student)['status'],'QUIT')
        self.assertEqual(self.schedules(),[])
        with self.db.transaction(True) as c:
            c.execute("UPDATE student SET status='DISABLED',disabled_by_credit=0 WHERE student_id='20260002'")
        self.s.set_student_credit(self.super,'20260002',8,1,'调整历史信用分')
        self.assertEqual(self.s.credit(self.demo['other_student'])['status'],'DISABLED')

    def test_super_can_set_all_credit_and_ordinary_admin_cannot(self):
        for actor in (self.normal,self.student):
            with self.assertRaises(DomainError):self.s.set_student_credit(actor,'20260002',9,1,'越权')
        self.s.set_student_credit(self.super,'20260002',9,1,'管理员核定')
        self.assertEqual(self.s.credit(self.demo['other_student'])['credit_score'],9)
        self.assertTrue(self.s.set_student_credit(self.super,'20260002',9,1,'重复')['replayed'])
        with self.assertRaises(DomainError):self.s.set_student_credit(self.super,'20260002',10,1,'过期页面')
        self.s.set_student_credit(self.super,'20260002',0,2,'暂停服务')
        self.assertEqual(self.s.credit(self.demo['other_student'])['status'],'DISABLED')
        self.s.set_student_credit(self.super,'20260002',5,3,'恢复信用')
        self.assertEqual(self.s.credit(self.demo['other_student'])['status'],'ACTIVE')
        self.assertEqual([r['entry_type'] for r in self.s.credit(self.demo['other_student'])['logs']],['MANUAL_SET']*3)

    def test_correction_scope_and_stale_revision(self):
        sid=self.absent()
        for actor in (self.student,self.demo['other_admin']):
            with self.assertRaises(DomainError):self.s.correct_attendance(actor,sid,'NORMAL','越权',1)
        self.s.correct_attendance(self.normal,sid,'LATE','改迟到',1)
        with self.assertRaises(DomainError):self.s.correct_attendance(self.normal,sid,'NORMAL','过期页面',1)
        with self.assertRaises(DomainError):self.s.correct_attendance(self.normal,sid,'NORMAL','',2)
        self.s.correct_attendance(self.super,sid,'NORMAL','超管核实',2)

    def test_concurrent_refunds_do_not_duplicate_credit(self):
        sid=self.absent()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.s.correct_attendance(self.normal,sid,'NORMAL','重复核实',1),range(2)))
        self.assertEqual(sum(bool(r.get('replayed')) for r in results),1)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.assertEqual(len(self.s.credit(self.student)['logs']),2)

    def test_correction_and_manual_set_audit_failure_roll_back_everything(self):
        sid=self.absent()
        before=self.s.credit(self.student)
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.s.correct_attendance(self.normal,sid,'NORMAL','误记',1)
            with self.assertRaises(RuntimeError):self.s.set_student_credit(self.super,self.student['id'],7,before['credit_version'],'手动调整')
        self.assertEqual(self.s.credit(self.student),before)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.assertEqual(self.rows('SELECT status FROM violation')[0]['status'],'VALID')
        self.assertEqual(self.rows('SELECT attendance_status,revision FROM attendance')[0],{'attendance_status':'ABSENT','revision':1})

    def test_http_revision_and_score_forms_are_validated_and_authorized(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service,identity
        sid=self.absent()
        app.dependency_overrides[get_service]=lambda:self.s
        app.dependency_overrides[identity]=lambda:self.normal
        try:
            with TestClient(app) as client:
                correction={'status':'NORMAL','reason':'误记','expected_revision':1}
                result=client.patch(f'/schedules/{sid}/attendance',json=correction)
                self.assertEqual(result.status_code,200,result.text)
                version=self.s.credit(self.student)['credit_version']
                score={'credit_score':8,'reason':'管理员核定','expected_version':version}
                self.assertEqual(client.put('/students/20260001/credit',json=score).status_code,403)
                app.dependency_overrides[identity]=lambda:self.super
                self.assertEqual(client.put('/students/20260001/credit',json={**score,'credit_score':-1}).status_code,422)
                self.assertEqual(client.put('/students/20260001/credit',json={**score,'student_id':'20260002'}).status_code,422)
                self.assertEqual(client.put('/students/20260001/credit',json=score).status_code,200)
        finally:app.dependency_overrides.clear()

    def test_later_membership_changes_do_not_backfill_the_new_slot(self):
        self.s.set_memberships(self.super,self.student['id'],[self.mon])
        self.term()
        self.now=datetime(2026,9,16,18)
        app=self.s.apply_fixed_transfer(self.student,self.mon,self.wed,'长期调整')['transfer_id']
        self.s.approve_transfer(self.normal,app,'first',True)
        self.s.approve_transfer(self.super,app,'final',True)
        self.s.run_weekly_settlement()
        rows=list(self.s.list_schedules(self.student))
        self.assertTrue(any(r['slot_id']==self.mon and r['schedule_date']==date(2026,9,7) and r['status']=='COMPLETED' for r in rows))
        self.assertFalse(any(r['slot_id']==self.wed and r['schedule_date']<date(2026,9,17) for r in rows))

    def test_past_pending_makeup_can_be_filled_and_settled_without_overwriting_history(self):
        self.now=datetime(2026,9,27,21)
        tid=self.term('2026-08-31',15)
        before=self.s.hours(self.student)['total_minutes']
        result=self.s.set_calendar(self.super,tid,'2026-09-20','2026-09-20','WEEKDAY',2,'补录周二调休班表')
        self.assertEqual(result['settled'],1)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],before+180)
        with self.assertRaises(DomainError):self.s.set_calendar(self.super,tid,'2026-09-20','2026-09-20','REST',reason='不能改写已结算服务')

    def test_super_can_record_unassigned_slot_attendance(self):
        self.term()
        sid=self.on('2026-09-07')
        with self.db.transaction(True) as c:c.execute('UPDATE service_slot SET manager_admin_id=NULL WHERE slot_id=%s',(self.mon,))
        self.now=datetime(2026,9,7,12)
        self.s.record_attendance(self.super,sid,'ABSENT','未分配负责人，由超管登记')
        self.s.correct_attendance(self.super,sid,'NORMAL','核实正常出勤',1)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)

    def test_upgrade_from_previous_schema_preserves_and_reverses_old_deductions(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from app import bootstrap
        from app.fixed_slots import migrate
        from app.db import one
        core=fixtures.CORE
        source=(core/'sql/schema.sql').read_text(encoding='utf-8')
        source=source.replace('    credit_version INT NOT NULL DEFAULT 1,\n','').replace('    disabled_by_credit TINYINT NOT NULL DEFAULT 0,\n','').replace('    revision INT NOT NULL DEFAULT 1,\n','')
        source=source.replace("    active_marker TINYINT GENERATED ALWAYS AS (CASE WHEN status='VALID' THEN 1 ELSE NULL END) STORED,\n    INDEX idx_violation_attendance (attendance_id),\n    UNIQUE KEY uq_violation_active (attendance_id,active_marker),",'    UNIQUE KEY uq_violation_attendance (attendance_id),')
        source=source.replace('    violation_id BIGINT UNSIGNED NULL,','    violation_id BIGINT UNSIGNED NOT NULL,').replace('    rule_id BIGINT UNSIGNED NULL,','    rule_id BIGINT UNSIGNED NOT NULL,')
        source=source.replace("    entry_type VARCHAR(24) NOT NULL DEFAULT 'DEDUCTION',\n    reverses_log_id BIGINT UNSIGNED NULL,\n",'')
        source=source.replace('    INDEX idx_credit_log_violation (violation_id),\n    UNIQUE KEY uq_credit_reversal (reverses_log_id),\n    CONSTRAINT fk_credit_reversal FOREIGN KEY (reverses_log_id) REFERENCES credit_log(credit_log_id),','    UNIQUE KEY uq_credit_log_violation (violation_id),')
        with TemporaryDirectory(dir=core.parent/'.work') as directory:
            legacy=Path(directory);(legacy/'sql').mkdir()
            (legacy/'sql/schema.sql').write_text(source,encoding='utf-8')
            (legacy/'sql/constraints.sql').write_text((core/'sql/constraints.sql').read_text(encoding='utf-8'),encoding='utf-8')
            with patch.object(bootstrap,'CORE',legacy):
                seed=bootstrap.initialize_database(self.settings,database='volunteer_core_test',reset=True)
        with self.db.transaction(True) as c:
            c.execute("INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date,status) VALUES('20260001',%s,%s,'2026-08-31','COMPLETED')",(seed['slot'],seed['normal']['id']))
            sid=c.lastrowid
            c.execute("INSERT INTO attendance(schedule_id,admin_id,attendance_status) VALUES(%s,%s,'ABSENT')",(sid,seed['normal']['id']))
            aid=c.lastrowid
            rule=one(c,"SELECT rule_id FROM credit_rule WHERE violation_type='ABSENT'")['rule_id']
            c.execute('INSERT INTO violation(attendance_id,rule_id,nominal_deduct) VALUES(%s,%s,3)',(aid,rule))
            vid=c.lastrowid
            c.execute("INSERT INTO credit_log(student_id,violation_id,rule_id,operator_id,change_score,before_score,after_score,change_reason) VALUES('20260001',%s,%s,%s,-2,2,0,'ABSENT')",(vid,rule,seed['normal']['id']))
            c.execute("UPDATE student SET credit_score=0,status='DISABLED' WHERE student_id='20260001'")
        migrate(self.settings);migrate(self.settings)
        result=self.s.correct_attendance(seed['normal'],sid,'NORMAL','修正升级前的错误记录',1)
        self.assertEqual(result['refunded_score'],2)
        self.assertEqual(self.s.credit(seed['student'])['status'],'ACTIVE')
        self.assertEqual(self.s.hours(seed['student'])['total_minutes'],120)


if __name__=='__main__':unittest.main()
