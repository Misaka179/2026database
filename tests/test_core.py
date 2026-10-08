"""Real MySQL integration tests for the volunteer-service workflows.

Run from core: python -m unittest discover -s tests -v
Every test recreates only the explicitly named volunteer_core_test database.
The development/demo database is never reset. No SQLite substitute is used.
"""
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1]
WORKSPACE = CORE.parent
sys.path.insert(0, str(CORE))

from app.bootstrap import initialize_database
from app.db import Database, one, all_rows
from app.service import DomainError, Service
import pymysql

TEST_DATABASE = 'volunteer_core_test'


class CoreIntegrationTests(unittest.TestCase):
    """Each test seeds its own database and uses an injected Shanghai clock."""

    @classmethod
    def setUpClass(cls):
        config_path = WORKSPACE / '.work/mysql-core/admin.json'
        if not config_path.exists():
            raise RuntimeError('真实 MySQL 未初始化，请先运行 scripts/local_mysql.py start')
        cls.admin_settings = json.loads(config_path.read_text(encoding='utf-8'))
        if not TEST_DATABASE.endswith('_test'):
            raise RuntimeError('拒绝重置非测试数据库')

    def setUp(self):
        self.demo = initialize_database(
            self.admin_settings, database=TEST_DATABASE, demo=True, reset=True)
        self.db = Database({**self.admin_settings, 'database': TEST_DATABASE})
        self.now = datetime(2030, 1, 1, 8, 0)
        self.service = Service(self.db, clock=lambda: self.now)
        self.super = self.demo['super']
        self.normal = self.demo['normal']
        self.other_admin = self.demo['other_admin']
        self.student = self.demo['student']
        self.other_student = self.demo['other_student']
        self.slot = self.make_slot()

    def make_slot(self, start='10:00', end='12:00', capacity=3,
                  manager=None, period=1):
        return self.service.create_slot(
            self.super, '测试分队', period, start, end, '测试服务地点',
            capacity, (manager or self.normal)['id'])['slot_id']

    def schedule(self, day='2030-01-02', student=None, slot=None):
        return self.service.create_schedule(
            self.super, (student or self.student)['id'],
            slot or self.slot, day)['schedule_id']

    def query_one(self, sql, args=()):
        with self.db.transaction() as c:
            return one(c, sql, args)

    def query_all(self, sql, args=()):
        with self.db.transaction() as c:
            return all_rows(c, sql, args)

    def count(self, table):
        # Table names only come from literals in this file.
        return self.query_one(f'SELECT COUNT(*) AS n FROM {table}')['n']

    def state(self, schedule_id):
        return self.query_one('SELECT status FROM schedule WHERE schedule_id=%s',
                              (schedule_id,))['status']

    def assert_domain(self, call, status=None):
        with self.assertRaises(DomainError) as caught:
            call()
        if status is not None:
            self.assertEqual(caught.exception.status, status)
        return caught.exception

    def parallel(self, *calls):
        barrier = threading.Barrier(len(calls))

        def execute(call):
            barrier.wait(timeout=10)
            try:
                return call()
            except DomainError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(execute, call) for call in calls]
            return [future.result(timeout=30) for future in futures]

    def fixed_pair(self, capacity=3):
        from app.fixed_slots import migrate
        migrate(self.db.settings)
        old = self.query_one('SELECT slot_id FROM service_slot WHERE weekday=1 AND period_no=1')['slot_id']
        target = self.query_one('SELECT slot_id FROM service_slot WHERE weekday=2 AND period_no=1')['slot_id']
        self.service.configure_slot(self.super, old, self.normal['id'], 20)
        self.service.configure_slot(self.super, target, self.other_admin['id'], capacity)
        self.service.set_memberships(self.super, self.student['id'], [old])
        return old, target

    def test_mysql_schema_has_thirteen_innodb_tables(self):
        rows = self.query_all('''SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ''', (TEST_DATABASE,))
        self.assertEqual(len(rows), 13)
        self.assertTrue(all(row['ENGINE'] == 'InnoDB' for row in rows))
        version = self.query_one('SELECT VERSION() AS version')['version']
        self.assertNotIn('sqlite', version.lower())

    def test_normal_attendance_creates_one_service_record(self):
        sid = self.schedule()
        self.now = datetime(2030, 1, 2, 12, 0)
        result = self.service.record_attendance(self.normal, sid, 'NORMAL')
        repeated = self.service.record_attendance(self.normal, sid, 'NORMAL')
        self.assertEqual(result['attendance_id'], repeated['attendance_id'])
        self.assertTrue(repeated['replayed'])
        self.assertEqual(self.count('attendance'), 1)
        self.assertEqual(self.count('service_record'), 1)
        self.assertEqual(self.count('violation'), 0)
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 120)
        self.assertEqual(self.state(sid), 'COMPLETED')
        self.assertEqual(self.service.credit(self.student)['credit_score'], 5)
        self.assert_domain(lambda: self.service.record_attendance(self.normal, sid, 'ABSENT'))

    def test_period_three_late_gets_full_three_hours_and_one_deduction(self):
        slot = self.make_slot(period=3)
        sid = self.schedule(slot=slot)
        self.now = datetime(2030, 1, 2, 12, 0)
        result = self.service.record_attendance(self.normal, sid, 'LATE')
        self.assertEqual(result['service_minutes'], 180)
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 180)
        credit = self.service.credit(self.student)
        self.assertEqual(credit['credit_score'], 3)
        self.assertEqual(len(credit['logs']), 1)
        self.assertEqual(credit['logs'][0]['change_score'], -2)

    def test_approved_leave_overrides_absence_without_hours_or_credit_loss(self):
        sid = self.schedule()
        lid = self.service.apply_leave(self.student, sid, '课程冲突')['leave_id']
        self.assert_domain(lambda: self.service.approve_leave(self.other_admin, lid, True), 403)
        self.service.approve_leave(self.normal, lid, True)
        self.assertTrue(self.service.approve_leave(self.normal, lid, True)['replayed'])
        self.now = datetime(2030, 1, 2, 12, 0)
        result = self.service.record_attendance(self.normal, sid, 'ABSENT')
        self.assertEqual(result['status'], 'LEAVE')
        self.assertEqual(self.service.record_attendance(self.normal, sid, 'NORMAL')['status'], 'LEAVE')
        self.assertEqual(self.count('service_record'), 0)
        self.assertEqual(self.count('violation'), 0)
        self.assertEqual(self.count('credit_log'), 0)
        self.assertEqual(self.service.credit(self.student)['credit_score'], 5)

    def test_rejected_leave_does_not_deduct_until_actual_absence(self):
        sid = self.schedule()
        lid = self.service.apply_leave(self.student, sid, '个人原因')['leave_id']
        self.service.approve_leave(self.normal, lid, False)
        self.assertEqual(self.service.credit(self.student)['credit_score'], 5)
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, sid, 'ABSENT')
        self.assertEqual(self.service.credit(self.student)['credit_score'], 2)

    def test_pending_leave_and_transfer_are_mutually_exclusive(self):
        sid = self.schedule()
        self.service.apply_leave(self.student, sid, '已有请假')
        self.assert_domain(lambda: self.service.apply_transfer(
            self.student, sid, self.slot, '2030-01-03', '换一天'))
        self.assertEqual(self.count('transfer_application'), 0)
        self.assert_domain(lambda: self.service.apply_leave(self.student, sid, '重复申请'))

    def test_attendance_time_guard_and_unapproved_leave_rejected(self):
        sid = self.schedule()
        self.assert_domain(lambda: self.service.record_attendance(self.normal, sid, 'NORMAL'))
        self.now = datetime(2030, 1, 2, 12, 0)
        self.assert_domain(lambda: self.service.record_attendance(self.normal, sid, 'LEAVE'))
        self.assertEqual(self.count('attendance'), 0)

    def test_student_and_normal_admin_cannot_cross_authorization_boundaries(self):
        sid = self.schedule()
        self.schedule(student=self.other_student)
        self.assert_domain(lambda: self.service.apply_leave(self.other_student, sid, '伪造申请'), 403)
        self.assert_domain(lambda: self.service.hours(self.student, self.other_student['id']), 403)
        self.assert_domain(lambda: self.service.credit(self.student, self.other_student['id']), 403)
        self.assert_domain(lambda: self.service.logs(self.normal), 403)
        self.assert_domain(lambda: self.service.rules(self.normal), 403)
        self.assert_domain(lambda: self.service.list_applications(self.normal, 'withdrawal'), 403)
        self.assert_domain(lambda: self.service.set_rule(self.normal, 'ABSENT', 1, '越权'), 403)
        self.assert_domain(lambda: self.service.create_schedule(
            self.other_admin, self.student['id'], self.slot, '2030-01-04'), 403)
        self.now = datetime(2030, 1, 2, 12, 0)
        self.assert_domain(lambda: self.service.record_attendance(self.other_admin, sid, 'NORMAL'), 403)
        self.assertEqual(self.service.record_attendance(self.super,sid,'NORMAL')['status'],'NORMAL')
        self.assert_domain(lambda: self.service.record_attendance(self.student, sid, 'NORMAL'), 403)
        own = self.service.list_schedules(self.student)
        self.assertTrue(own)
        self.assertTrue(all(row['student_id'] == self.student['id'] for row in own))

    def test_actor_supplied_role_does_not_escalate_and_disabled_admin_is_rejected(self):
        forged = {**self.normal, 'role': 'SUPER'}
        self.assert_domain(lambda: self.service.set_rule(forged, 'ABSENT', 1, '伪造角色'), 403)
        with self.db.transaction(True) as c:
            c.execute("UPDATE admin SET status='DISABLED' WHERE admin_id=%s", (self.normal['id'],))
        self.assert_domain(lambda: self.service.list_schedules(self.normal), 403)

    def test_single_date_transfer_is_disabled_without_changing_schedule(self):
        sid = self.schedule()
        error=self.assert_domain(lambda:self.service.apply_transfer(self.student,sid,self.slot,'2030-01-03','单次换班'),410)
        self.assertIn('长期',error.message)
        self.assertEqual(self.count('transfer_application'),0)
        self.assertEqual(self.state(sid),'ACTIVE')

    def test_fixed_transfer_rejection_retains_original_membership(self):
        old,target=self.fixed_pair()
        tid=self.service.apply_fixed_transfer(self.student,old,target,'长期调整')['transfer_id']
        self.service.approve_transfer(self.normal,tid,'first',False)
        self.assert_domain(lambda:self.service.approve_transfer(self.super,tid,'final',True))
        self.assertEqual([r['slot_id'] for r in self.service.my_memberships(self.student)],[old])

    def test_capacity_is_per_date_and_overlap_uses_actual_time(self):
        limited = self.make_slot(capacity=1)
        self.schedule(slot=limited)
        self.assert_domain(lambda: self.schedule(student=self.other_student, slot=limited))
        self.schedule('2030-01-03', student=self.other_student, slot=limited)
        overlap = self.make_slot('11:00', '13:00')
        self.assert_domain(lambda: self.schedule(slot=overlap))
        adjacent = self.make_slot('12:00', '14:00')
        self.schedule(slot=adjacent)
        self.assertEqual(self.count('schedule'), 3)

    def test_fixed_transfer_revalidates_capacity_at_final_approval(self):
        old,target=self.fixed_pair(capacity=1)
        tid=self.service.apply_fixed_transfer(self.student,old,target,'长期调整')['transfer_id']
        self.service.approve_transfer(self.normal,tid,'first',True)
        self.service.set_memberships(self.super,self.other_student['id'],[target])
        self.assert_domain(lambda:self.service.approve_transfer(self.super,tid,'final',True))
        self.assertEqual(self.query_one('SELECT final_status FROM transfer_application WHERE transfer_id=%s',(tid,))['final_status'],'PENDING')
        self.assertEqual([r['slot_id'] for r in self.service.my_memberships(self.student)],[old])

    def test_parallel_fixed_transfers_cannot_overbook_last_place(self):
        old,target=self.fixed_pair(capacity=1)
        self.service.set_memberships(self.super,self.other_student['id'],[old])
        tids=[]
        for student in (self.student,self.other_student):
            tid=self.service.apply_fixed_transfer(student,old,target,'长期争取名额')['transfer_id']
            self.service.approve_transfer(self.normal,tid,'first',True)
            tids.append(tid)
        results=self.parallel(*[lambda tid=tid:self.service.approve_transfer(self.super,tid,'final',True) for tid in tids])
        self.assertEqual(sum(isinstance(r,DomainError) for r in results),1)
        self.assertEqual(self.query_one('SELECT COUNT(*) n FROM slot_member WHERE slot_id=%s',(target,))['n'],1)

    def test_parallel_repeated_absence_deducts_only_once(self):
        sid = self.schedule()
        self.now = datetime(2030, 1, 2, 12, 0)
        results = self.parallel(*[
            lambda: self.service.record_attendance(self.normal, sid, 'ABSENT') for _ in range(3)])
        self.assertTrue(all(isinstance(r, dict) for r in results))
        self.assertEqual(sum(bool(r.get('replayed')) for r in results), 2)
        self.assertEqual(self.count('attendance'), 1)
        self.assertEqual(self.count('violation'), 1)
        self.assertEqual(self.count('credit_log'), 1)
        self.assertEqual(self.service.credit(self.student)['credit_score'], 2)

    def test_parallel_distinct_deductions_have_no_lost_update_and_floor_at_zero(self):
        first = self.schedule()
        second = self.schedule('2030-01-03')
        future = self.schedule('2030-01-05')
        lid = self.service.apply_leave(self.student, future, '后续请假')['leave_id']
        self.now = datetime(2030, 1, 4, 8, 0)
        results = self.parallel(
            lambda: self.service.record_attendance(self.normal, first, 'ABSENT'),
            lambda: self.service.record_attendance(self.normal, second, 'ABSENT'))
        self.assertTrue(all(isinstance(r, dict) for r in results))
        credit = self.service.credit(self.student)
        self.assertEqual((credit['credit_score'], credit['status']), (0, 'DISABLED'))
        self.assertEqual([r['change_score'] for r in credit['logs']], [-3, -2])
        self.assertEqual([(r['before_score'], r['after_score']) for r in credit['logs']], [(5, 2), (2, 0)])
        self.assertEqual(self.state(future), 'CANCELLED')
        self.assertEqual(self.query_one('SELECT approve_status FROM leave_application WHERE leave_id=%s', (lid,))['approve_status'], 'CANCELLED')
        self.assert_domain(lambda: self.schedule('2030-01-06'))
        self.assert_domain(lambda: self.service.apply_withdrawal(self.student, '已停用后申请'), 403)
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 0)

    def test_rule_change_preserves_old_deduction_and_records_new_version(self):
        first = self.schedule()
        second = self.schedule('2030-01-03')
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, first, 'LATE')
        first_log = self.service.credit(self.student)['logs'][0]
        new_rule = self.service.set_rule(self.super, 'LATE', 1, '新规定迟到扣 1 分')
        self.now = datetime(2030, 1, 3, 12, 0)
        self.service.record_attendance(self.normal, second, 'LATE')
        logs = self.service.credit(self.student)['logs']
        self.assertEqual([r['change_score'] for r in logs], [-2, -1])
        self.assertEqual(logs[0]['rule_id'], first_log['rule_id'])
        self.assertEqual(logs[1]['rule_id'], new_rule['rule_id'])
        old_rule = self.query_one('SELECT * FROM credit_rule WHERE rule_id=%s', (first_log['rule_id'],))
        self.assertEqual((old_rule['deduct_score'], old_rule['status']), (2, 'RETIRED'))
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 240)

    def test_missing_credit_rule_rolls_back_entire_attendance(self):
        sid = self.schedule()
        with self.db.transaction(True) as c:
            c.execute("UPDATE credit_rule SET status='RETIRED' WHERE violation_type='LATE'")
        self.now = datetime(2030, 1, 2, 12, 0)
        self.assert_domain(lambda: self.service.record_attendance(self.normal, sid, 'LATE'))
        self.assertEqual(self.state(sid), 'ACTIVE')
        self.assertEqual(self.count('attendance'), 0)
        self.assertEqual(self.count('service_record'), 0)
        self.assertEqual(self.count('violation'), 0)
        self.assertEqual(self.count('credit_log'), 0)
        self.assertEqual(self.service.credit(self.student)['credit_score'], 5)

    def test_attendance_audit_failure_rolls_back_real_mysql_writes(self):
        sid = self.schedule()
        self.now = datetime(2030, 1, 2, 12, 0)
        old_logs = self.count('operation_log')
        with patch.object(self.service, 'audit', side_effect=RuntimeError('模拟日志写入失败')):
            with self.assertRaisesRegex(RuntimeError, '模拟日志写入失败'):
                self.service.record_attendance(self.normal, sid, 'LATE')
        for table in ('attendance', 'service_record', 'violation', 'credit_log'):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(self.state(sid), 'ACTIVE')
        self.assertEqual(self.service.credit(self.student)['credit_score'], 5)
        self.assertEqual(self.count('operation_log'), old_logs)
        self.service.record_attendance(self.normal, sid, 'LATE')
        self.assertEqual(self.service.credit(self.student)['credit_score'], 3)

    def test_fixed_transfer_audit_failure_rolls_back_membership_and_status(self):
        old,target=self.fixed_pair()
        tid=self.service.apply_fixed_transfer(self.student,old,target,'长期调整')['transfer_id']
        self.service.approve_transfer(self.normal,tid,'first',True)
        with patch.object(self.service,'audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.service.approve_transfer(self.super,tid,'final',True)
        self.assertEqual([r['slot_id'] for r in self.service.my_memberships(self.student)],[old])
        self.assertEqual(self.query_one('SELECT final_status FROM transfer_application WHERE transfer_id=%s',(tid,))['final_status'],'PENDING')

    def test_hours_revision_is_authorized_audited_and_atomic(self):
        sid = self.schedule()
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, sid, 'NORMAL')
        record_id = self.service.hours(self.student)['records'][0]['record_id']
        self.assert_domain(lambda: self.service.revise_hours(self.normal, record_id, 180, '越权'), 403)
        self.assert_domain(lambda: self.service.revise_hours(self.student, record_id, 180, '越权'), 403)
        self.service.revise_hours(self.super, record_id, 180, '核对后补录 1 小时')
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 180)
        log = self.service.logs(self.super)[0]
        self.assertEqual(log['operation_type'], 'REVISE_HOURS')
        self.assertEqual(json.loads(log['before_value'])['service_minutes'], 120)
        self.assertEqual(json.loads(log['after_value'])['service_minutes'], 180)
        with patch.object(self.service, 'audit', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.service.revise_hours(self.super, record_id, 240, '故障回滚')
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 180)

    def test_hours_filter_excludes_end_date_void_records_and_other_students(self):
        own_first = self.schedule()
        own_second = self.schedule('2030-01-03')
        other = self.schedule(student=self.other_student)
        self.now = datetime(2030, 1, 4, 8, 0)
        for sid in (own_first, own_second, other):
            self.service.record_attendance(self.normal, sid, 'NORMAL')
        self.assertEqual(self.service.hours(self.student, start='2030-01-02', end='2030-01-03')['total_minutes'], 120)
        with self.db.transaction(True) as c:
            c.execute("UPDATE service_record r JOIN attendance a ON a.attendance_id=r.attendance_id SET r.record_status='VOID' WHERE a.schedule_id=%s", (own_first,))
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 120)
        self.assertEqual(self.service.hours(self.student, start='2030-02-01', end='2030-03-01')['total_minutes'], 0)

    def test_withdrawal_preserves_history_and_cancels_today_and_future(self):
        past = self.schedule()
        same_day_slot = self.make_slot('14:00', '16:00')
        today = self.schedule(slot=same_day_slot)
        future = self.schedule('2030-01-03')
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, past, 'LATE')
        wid = self.service.apply_withdrawal(self.student, '学业安排')['withdrawal_id']
        self.assert_domain(lambda: self.service.approve_withdrawal(self.normal, wid, True), 403)
        self.service.approve_withdrawal(self.super, wid, True)
        self.assertTrue(self.service.approve_withdrawal(self.super, wid, True)['replayed'])
        self.assertEqual(self.state(past), 'COMPLETED')
        self.assertEqual(self.state(today), 'CANCELLED')
        self.assertEqual(self.state(future), 'CANCELLED')
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 120)
        credit = self.service.credit(self.student)
        self.assertEqual((credit['status'], credit['credit_score'], len(credit['logs'])), ('QUIT', 3, 1))
        self.assert_domain(lambda: self.schedule('2030-01-04'))
        self.assertGreater(self.count('operation_log'), 0)

    def test_expired_pending_leave_cannot_be_approved_after_absence(self):
        sid = self.schedule()
        lid = self.service.apply_leave(self.student, sid, '未及时审批')['leave_id']
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, sid, 'ABSENT')
        self.assert_domain(lambda: self.service.approve_leave(self.normal, lid, True))
        self.assertEqual(self.service.credit(self.student)['credit_score'], 2)
        self.assertEqual(self.count('credit_log'), 1)

    def test_mysql_rejects_invalid_foreign_keys_and_cross_student_application(self):
        sid = self.schedule()
        statements = [
            ('''INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date)
                VALUES(%s,%s,%s,'2030-01-03')''',
             ('nonexistent_student', self.slot, self.super['id'])),
            ('''INSERT INTO leave_application(student_id,schedule_id,reason)
                VALUES(%s,%s,'冒用其他学生排班')''',
             (self.other_student['id'], sid)),
            ('''INSERT INTO transfer_application(student_id,old_schedule_id,new_slot_id,new_date,reason)
                VALUES(%s,%s,%s,'2030-01-03','冒用其他学生排班')''',
             (self.other_student['id'], sid, self.slot)),
        ]
        for sql, args in statements:
            with self.subTest(sql=sql.split()[2]):
                with self.assertRaises(pymysql.MySQLError):
                    with self.db.transaction(True) as c:
                        c.execute(sql, args)
        self.assertEqual(self.count('schedule'), 1)
        self.assertEqual(self.count('leave_application'), 0)
        self.assertEqual(self.count('transfer_application'), 0)

    def test_mysql_enforces_nonnegative_credit_minutes_and_credit_arithmetic(self):
        sid = self.schedule()
        self.now = datetime(2030, 1, 2, 12, 0)
        self.service.record_attendance(self.normal, sid, 'LATE')
        record_id = self.service.hours(self.student)['records'][0]['record_id']
        log_id = self.service.credit(self.student)['logs'][0]['credit_log_id']
        statements = [
            ('UPDATE student SET credit_score=-1 WHERE student_id=%s', (self.student['id'],)),
            ('UPDATE service_record SET service_minutes=-1 WHERE record_id=%s', (record_id,)),
            ('UPDATE credit_log SET after_score=after_score+1 WHERE credit_log_id=%s', (log_id,)),
        ]
        for sql, args in statements:
            with self.subTest(sql=sql):
                with self.assertRaises(pymysql.MySQLError):
                    with self.db.transaction(True) as c:
                        c.execute(sql, args)
        self.assertEqual(self.service.credit(self.student)['credit_score'], 3)
        self.assertEqual(self.service.hours(self.student)['total_minutes'], 120)
        log = self.service.credit(self.student)['logs'][0]
        self.assertEqual(log['before_score'] + log['change_score'], log['after_score'])

    def test_fixed_transfer_rechecks_target_ownership_at_final_approval(self):
        old,target=self.fixed_pair()
        tid=self.service.apply_fixed_transfer(self.student,old,target,'长期调整')['transfer_id']
        self.service.approve_transfer(self.normal,tid,'first',True)
        self.service.set_memberships(self.super,self.student['id'],[old,target])
        self.assert_domain(lambda:self.service.approve_transfer(self.super,tid,'final',True))
        self.assertEqual(self.query_one('SELECT final_status FROM transfer_application WHERE transfer_id=%s',(tid,))['final_status'],'PENDING')

    def test_withdrawal_audit_failure_preserves_student_and_future_schedules(self):
        future = self.schedule()
        wid = self.service.apply_withdrawal(self.student, '退出申请')['withdrawal_id']
        with patch.object(self.service, 'audit', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.service.approve_withdrawal(self.super, wid, True)
        self.assertEqual(self.state(future), 'ACTIVE')
        self.assertEqual(self.service.credit(self.student)['status'], 'ACTIVE')
        self.assertEqual(self.query_one('SELECT approve_status FROM withdrawal_application WHERE withdrawal_id=%s', (wid,))['approve_status'], 'PENDING')


if __name__ == '__main__':
    unittest.main(verbosity=2)
