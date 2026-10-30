"""Semester workflows use real MySQL and an injected clock, never production data."""
import json
import os
from pathlib import Path
import sys
import unittest
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'
from app.bootstrap import initialize_database
from app.fixed_slots import migrate
from app.db import Database, one, all_rows
from app.service import Service, DomainError
from app.semester import default_day, end_date


import base64
from io import BytesIO
from PIL import Image
_image=BytesIO();Image.new('RGB',(2,2),'white').save(_image,format='PNG')
TEST_IMAGES=[base64.b64encode(_image.getvalue()).decode()]

class CalendarRulesTests(unittest.TestCase):
    def test_scheduler_runs_on_startup_and_again_after_restart(self):
        import threading
        from fastapi.testclient import TestClient
        from app.api import app, get_service
        event=threading.Event()
        class Worker:
            calls=0
            def run_weekly_settlement(self):
                self.calls+=1
                event.set()
        worker=Worker()
        app.dependency_overrides[get_service]=lambda:worker
        try:
            with patch.dict(os.environ,{'VOLUNTEER_DISABLE_SCHEDULER':'0'}):
                for _ in range(2):
                    event.clear()
                    with TestClient(app):
                        self.assertTrue(event.wait(5))
            self.assertEqual(worker.calls,2)
        finally:app.dependency_overrides.clear()

    def test_holidays_makeup_weekends_and_unknown_year(self):
        self.assertEqual(default_day(date(2026, 10, 1))[:2], ('HOLIDAY', None))
        self.assertEqual(default_day(date(2026, 10, 10))[:2], ('MAKEUP_REQUIRED', None))
        self.assertEqual(default_day(date(2026, 9, 12))[:2], ('NORMAL', 6))
        self.assertEqual(default_day(date(2027, 1, 1))[:2], ('UNCONFIRMED', None))
        self.assertEqual(end_date(date(2026, 9, 9), 2), date(2026, 9, 20))


class SemesterTests(unittest.TestCase):
    def setUp(self):
        cfg = json.loads((CORE.parent / '.work/mysql-core/admin.json').read_text(encoding='utf-8'))
        self.demo = initialize_database(cfg, database='volunteer_core_test', reset=True)
        self.settings = {**cfg, 'database': 'volunteer_core_test'}
        migrate(self.settings)
        self.db = Database(self.settings)
        self.now = datetime(2026, 9, 6, 7)
        self.s = Service(self.db, clock=lambda: self.now)
        self.super, self.normal, self.student = (self.demo[k] for k in ('super', 'normal', 'student'))
        with self.db.transaction() as c:
            self.slots = {(r['weekday'], r['period_no']): r['slot_id'] for r in all_rows(c, 'SELECT * FROM service_slot WHERE weekday IS NOT NULL AND business_id=(SELECT business_id FROM business WHERE code=\'CONSULT\')')}
        self.mon, self.tue, self.wed, self.sat = [self.slots[p] for p in [(1,1), (2,3), (3,1), (6,1)]]
        for slot in (self.mon, self.tue, self.wed, self.sat):
            self.s.configure_slot(self.super, slot, self.normal['id'], 20)
        self.s.set_memberships(self.super, self.student['id'], [self.mon])
        # Legacy multi-team fixture predates the one-consultation-team constraint.
        # Keep it as historical data for settlement and migration regressions.
        with self.db.transaction(True) as c:
            for slot in (self.tue,self.sat):
                c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(self.student['id'],slot))

    def term(self, start='2026-09-07', weeks=3):
        return self.s.save_semester(self.super, '测试学期', start, weeks)['semester_id']

    def rows(self, sql, args=()):
        with self.db.transaction() as c:
            return list(all_rows(c, sql, args))

    def schedules(self, status='ACTIVE'):
        return [r for r in self.s.list_schedules(self.student) if r['status'] == status]

    def on(self, day, slot=None):
        return next(r for r in self.schedules() if str(r['schedule_date']) == day and (slot is None or r['slot_id']==slot))['schedule_id']

    def test_full_term_snapshot_holidays_and_idempotent_sync(self):
        tid = self.term()
        rows = self.schedules()
        self.assertEqual(len(rows), 8)  # 9/26 is Mid-autumn holiday; ordinary Saturday works.
        self.assertEqual({r['week_no'] for r in rows}, {1,2,3})
        self.assertNotIn(date(2026,9,26), [r['schedule_date'] for r in rows])
        self.assertEqual(self.s.sync_calendar(self.super, tid)['created'], 0)
        migrate(self.settings)
        self.assertEqual(len(self.schedules()), 8)

    def test_week_boundary_auto_hours_restart_and_parallel_replay(self):
        self.term()
        self.now = datetime(2026,9,13,23,59,59)
        self.assertEqual(self.s.run_weekly_settlement()['settled'], 0)
        self.now = datetime(2026,9,14)
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _: self.s.run_weekly_settlement(), range(2)))
        self.assertEqual(sum(r['settled'] for r in results), 3)
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 420)
        self.assertEqual(self.s.run_weekly_settlement()['settled'], 0)
        self.now = datetime(2026,10,5)
        self.assertEqual(self.s.run_weekly_settlement()['settled'], 5)
        self.assertEqual(len(self.schedules('COMPLETED')), 8)
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 1140)

    def test_absence_late_and_approved_leave_not_overwritten(self):
        self.term()
        mon, tue, sat = self.on('2026-09-07'), self.on('2026-09-08'), self.on('2026-09-12')
        lid=self.s.apply_leave(self.student, sat, '请假',images=TEST_IMAGES)['leave_id']
        self.s.approve_leave(self.normal,lid,True)
        self.now=datetime(2026,9,7,12)
        self.s.record_attendance(self.normal,mon,'ABSENT')
        self.now=datetime(2026,9,8,17)
        self.s.record_attendance(self.normal,tue,'LATE')
        # Absence (3) + late (1) leaves one credit; approved leave remains exempt.
        self.now=datetime(2026,9,14)
        self.s.run_weekly_settlement()
        self.assertEqual(self.s.hours(self.student)['total_minutes'],180)
        self.assertEqual(self.s.credit(self.student)['credit_score'],1)
        self.assertTrue(self.schedules())

    def test_approved_leave_automatically_settles_without_hours_or_penalty(self):
        self.term()
        lid=self.s.apply_leave(self.student,self.on('2026-09-08'),'课程请假',images=TEST_IMAGES)['leave_id']
        self.s.approve_leave(self.normal,lid,True)
        self.now=datetime(2026,9,14)
        self.s.run_weekly_settlement()
        self.assertEqual(self.s.hours(self.student)['total_minutes'],240)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.assertEqual(sum(r['attendance_status']=='LEAVE' for r in self.schedules('COMPLETED')),1)

    def test_late_reported_absence_reverses_auto_hours_once(self):
        self.term()
        sid=self.on('2026-09-07')
        self.now=datetime(2026,9,14)
        self.s.run_weekly_settlement()
        with self.assertRaises(DomainError): self.s.record_attendance(self.normal,sid,'ABSENT')
        self.s.record_attendance(self.normal,sid,'ABSENT','补录缺勤')
        self.assertTrue(self.s.record_attendance(self.normal,sid,'ABSENT','重试')['replayed'])
        self.assertEqual(self.s.hours(self.student)['total_minutes'],300)
        self.assertEqual(self.s.credit(self.student)['credit_score'],2)
        with self.assertRaises(DomainError): self.s.record_attendance(self.normal,sid,'NORMAL')

    def test_calendar_makeup_changes_real_date_and_default_restore(self):
        tid=self.term('2026-09-07',6)
        self.assertFalse(any(r['schedule_date']==date(2026,10,10) for r in self.schedules()))
        result=self.s.set_calendar(self.super,tid,'2026-10-10','2026-10-10','WEEKDAY',2,'国庆调休按周二')
        self.assertEqual(result['created'],1)
        sid=self.on('2026-10-10')
        self.assertEqual(next(r for r in self.schedules() if r['schedule_id']==sid)['slot_id'],self.tue)
        with self.assertRaises(DomainError):self.s.create_schedule(self.super,'20260002',self.mon,'2026-10-10')
        with self.assertRaises(DomainError):self.s.create_schedule(self.super,'20260002',self.tue,'2026-10-06')
        self.s.set_calendar(self.super,tid,'2026-10-10','2026-10-10','DEFAULT',reason='撤销调休映射')
        self.assertFalse(any(r['schedule_date']==date(2026,10,10) for r in self.schedules()))

    def test_rest_cancels_affected_leave_only_and_unchanged_ids_survive(self):
        tid=self.term()
        mon,tue=self.on('2026-09-07'),self.on('2026-09-08')
        lid=self.s.apply_leave(self.student,mon,'请假',images=TEST_IMAGES)['leave_id']
        self.s.set_calendar(self.super,tid,'2026-09-07','2026-09-07','REST',reason='学校停工')
        self.assertEqual(self.s.list_applications(self.student,'leave')[0]['approve_status'],'CANCELLED')
        self.assertEqual(self.on('2026-09-08'),tue)
        self.s.set_calendar(self.super,tid,'2026-09-07','2026-09-07','DEFAULT',reason='恢复上工')
        self.assertNotEqual(self.on('2026-09-07'),mon)

    def test_manual_cancel_not_resurrected_and_end_week_can_change(self):
        tid=self.term()
        sid=self.on('2026-09-07')
        self.s.cancel_schedule(self.normal,sid,'例外取消')
        self.s.sync_calendar(self.super,tid)
        self.assertFalse(any(r['schedule_id']==sid for r in self.schedules()))
        self.s.save_semester(self.super,'测试学期','2026-09-07',1,tid)
        self.assertTrue(all(r['week_no']==1 for r in self.schedules()))
        self.s.save_semester(self.super,'测试学期','2026-09-07',2,tid)
        self.assertEqual(len(self.schedules()),5)

    def test_transfer_updates_future_not_started_or_historical_work(self):
        self.s.set_memberships(self.super,self.student['id'],[self.mon])
        self.term()
        old=self.on('2026-09-07')
        self.now=datetime(2026,9,7,8,30)
        app=self.s.apply_fixed_transfer(self.student,self.mon,self.wed,'长期调时段')['transfer_id']
        self.s.approve_transfer(self.normal,app,'first',True)
        self.s.approve_transfer(self.super,app,'final',True)
        rows=self.schedules()
        self.assertTrue(any(r['schedule_id']==old for r in rows))
        self.assertEqual(sum(r['slot_id']==self.mon for r in rows),1)
        self.assertEqual(sum(r['slot_id']==self.wed for r in rows),3)

    def test_transfer_calendar_and_settlement_failures_roll_back(self):
        self.s.set_memberships(self.super,self.student['id'],[self.mon])
        tid=self.term()
        before=self.schedules()
        app=self.s.apply_fixed_transfer(self.student,self.mon,self.wed,'长期调时段')['transfer_id']
        self.s.approve_transfer(self.normal,app,'first',True)
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError): self.s.approve_transfer(self.super,app,'final',True)
            with self.assertRaises(RuntimeError): self.s.set_calendar(self.super,tid,'2026-09-07','2026-09-07','REST',reason='停工')
            self.now=datetime(2026,9,14)
            with self.assertRaises(RuntimeError): self.s.run_weekly_settlement()
        self.assertEqual(self.schedules(),before)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.assertIn(self.mon,[s['slot_id'] for s in self.s.my_memberships(self.student)])

    def test_midterm_configuration_backfills_initial_roster_but_dates_new_members(self):
        self.now=datetime(2026,9,16,18)
        self.term()
        self.assertEqual(len(self.schedules('COMPLETED')),3)
        self.s.run_weekly_settlement()
        self.assertEqual(self.s.hours(self.student)['total_minutes'],420)
        self.s.set_memberships(self.super,'20260002',[self.mon])
        rows=self.s.list_schedules(self.demo['other_student'])
        self.assertEqual([r['schedule_date'] for r in rows],[date(2026,9,21)])

    def test_unknown_year_blocks_until_administrator_confirms_calendar(self):
        tid=self.term('2027-01-04',1)
        self.assertEqual(self.schedules(),[])
        self.assertTrue(self.s.semesters(self.super)[0]['issues'])
        self.s.set_calendar(self.super,tid,'2027-01-04','2027-01-10','NATURAL',reason='已核对该周无假期')
        self.assertEqual(len(self.schedules()),3)

    def test_scope_overlap_past_date_and_start_guards(self):
        for actor in (self.normal,self.student):
            with self.assertRaises(DomainError):self.s.save_semester(actor,'越权','2026-09-07',3)
        tid=self.term()
        with self.assertRaises(DomainError):self.term('2026-09-21',2)
        with self.assertRaises(DomainError):self.s.set_calendar(self.normal,tid,'2026-09-07','2026-09-07','REST',reason='越权')
        self.now=datetime(2026,9,7,9)
        with self.assertRaises(DomainError):self.s.set_calendar(self.super,tid,'2026-09-07','2026-09-07','REST',reason='已开工')
        with self.assertRaises(DomainError):self.s.save_semester(self.super,'测试学期','2026-09-08',3,tid)

    def test_calendar_http_create_edit_validation_and_scope(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service,identity
        app.dependency_overrides[get_service]=lambda:self.s
        app.dependency_overrides[identity]=lambda:self.super
        try:
            with TestClient(app) as client:
                body={'name':'接口测试学期','start_date':'2026-09-07','end_week':3}
                response=client.post('/semesters',json=body)
                self.assertEqual(response.status_code,200,response.text)
                tid=response.json()['semester_id']
                self.assertEqual(response.json()['end_date'],'2026-09-27')
                self.assertEqual(client.put(f'/semesters/{tid}',json={**body,'end_week':2}).status_code,200)
                self.assertEqual(client.put(f'/semesters/{tid}',json={**body,'end_week':0}).status_code,422)
                calendar={'start_date':'2026-09-12','end_date':'2026-09-12','mode':'WEEKDAY','weekday':2,'reason':'学校调课'}
                self.assertEqual(client.put(f'/semesters/{tid}/calendar',json=calendar).status_code,200)
                self.assertEqual(client.put(f'/semesters/{tid}/calendar',json={**calendar,'weekday':None}).status_code,422)
                self.assertEqual(client.post(f'/semesters/{tid}/sync',json={}).json()['created'],0)
                app.dependency_overrides[identity]=lambda:self.normal
                self.assertEqual(client.get('/semesters').status_code,200)
                self.assertEqual(client.put(f'/semesters/{tid}/calendar',json=calendar).status_code,403)
                self.assertEqual(client.post(f'/semesters/{tid}/sync',json={}).status_code,403)
        finally:app.dependency_overrides.clear()

    def test_final_transfer_rechecks_conflicting_dated_assignment_atomically(self):
        self.s.set_memberships(self.super,self.student['id'],[self.mon])
        self.term()
        app=self.s.apply_fixed_transfer(self.student,self.mon,self.wed,'长期调整')['transfer_id']
        self.s.approve_transfer(self.normal,app,'first',True)
        # A legacy manual occurrence conflicts with the target on a future day.
        with self.db.transaction(True) as c:
            c.execute("INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date) VALUES(%s,%s,%s,'2026-09-09')",(self.student['id'],self.mon,self.normal['id']))
        before=self.schedules()
        with self.assertRaisesRegex(DomainError,'时间冲突'):self.s.approve_transfer(self.super,app,'final',True)
        self.assertEqual(self.schedules(),before)
        self.assertIn(self.mon,[r['slot_id'] for r in self.s.my_memberships(self.student)])

    def test_single_transfer_disabled_in_service_api_and_legacy_approval(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service,identity
        self.term()
        sid=self.on('2026-09-07')
        with self.assertRaises(DomainError) as error:self.s.apply_transfer(self.student,sid,self.wed,'2026-09-09','单次')
        self.assertEqual(error.exception.status,410)
        app.dependency_overrides[get_service]=lambda:self.s
        app.dependency_overrides[identity]=lambda:self.student
        try:
            with TestClient(app) as client:
                self.assertEqual(client.post('/applications/transfer',json={'old_schedule_id':sid,'new_slot_id':self.wed,'new_date':'2026-09-09','reason':'单次'}).status_code,410)
                self.assertEqual(client.post('/semesters',json={'name':'越权','start_date':'2027-01-01','end_week':2}).status_code,403)
                self.assertEqual(client.get('/semesters').status_code,200)
        finally:app.dependency_overrides.clear()
        with self.db.transaction(True) as c:
            c.execute('INSERT INTO transfer_application(student_id,old_schedule_id,new_slot_id,new_date,reason) VALUES(%s,%s,%s,%s,%s)',(self.student['id'],sid,self.wed,'2026-09-09','历史单次申请'))
            aid=c.lastrowid
        with self.assertRaises(DomainError) as error:self.s.approve_transfer(self.normal,aid,'first',True)
        self.assertEqual(error.exception.status,410)
        migrate(self.settings)
        self.assertEqual(self.s.list_applications(self.student,'transfer')[0]['final_status'],'CANCELLED')


if __name__=='__main__':unittest.main()
