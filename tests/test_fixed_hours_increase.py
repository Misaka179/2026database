"""Fixed-slot increases preserve settlement timing and permission boundaries."""
import unittest
from datetime import datetime
from unittest.mock import patch
from test_semester import SemesterTests
from app.service import DomainError


class FixedHoursIncreaseTests(unittest.TestCase):
    setUp = SemesterTests.setUp
    rows = SemesterTests.rows
    term = SemesterTests.term

    def ended(self):
        self.term()
        self.now = datetime(2026, 9, 7, 23)
        return next(r for r in self.s.list_schedules(self.student)
                    if str(r['schedule_date']) == '2026-09-07')

    def test_weekly_override_and_notification_are_idempotent(self):
        row = self.ended()
        result = self.s.increase_fixed_hours(self.normal, row['schedule_id'], 150, 120, '延长服务')
        self.assertFalse(result['settled'])
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 0)
        self.assertEqual(len(self.rows("SELECT * FROM inbox_notice WHERE title='时段管理员上调服务时长'")), 1)
        with self.assertRaises(DomainError):
            self.s.increase_fixed_hours(self.normal, row['schedule_id'], 150, 120, '重试')
        self.now = datetime(2026, 9, 14)
        self.s.run_weekly_settlement()
        self.s.run_weekly_settlement()
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 450)

    def test_settled_increase_and_correction_restores_standard(self):
        row = self.ended()
        self.s.record_attendance(self.normal, row['schedule_id'], 'NORMAL')
        result = self.s.increase_fixed_hours(self.normal, row['schedule_id'], 160, 120, '延长服务')
        self.assertTrue(result['settled'])
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 160)
        self.s.correct_attendance(self.normal, row['schedule_id'], 'LATE', '考勤更正', 1)
        self.assertEqual(self.s.hours(self.student)['total_minutes'], 120)
        self.assertIsNone(self.rows('SELECT recognition_minutes FROM schedule WHERE schedule_id=%s', (row['schedule_id'],))[0]['recognition_minutes'])

    def test_invalid_scope_state_and_rollback(self):
        row = self.ended()
        for actor in (self.super, self.student):
            with self.assertRaises(DomainError):
                self.s.increase_fixed_hours(actor, row['schedule_id'], 150, 120, '无权操作')
        for value, expected, reason in ((120,120,'相同'),(100,120,'降低'),(150,100,'过期'),(150,120,' '),(1441,120,'超限')):
            with self.assertRaises(DomainError):
                self.s.increase_fixed_hours(self.normal, row['schedule_id'], value, expected, reason)
        with patch.object(self.s, 'audit', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                self.s.increase_fixed_hours(self.normal, row['schedule_id'], 150, 120, '回滚')
        self.assertIsNone(self.rows('SELECT recognition_minutes FROM schedule WHERE schedule_id=%s', (row['schedule_id'],))[0]['recognition_minutes'])
        self.s.record_attendance(self.normal, row['schedule_id'], 'ABSENT')
        with self.assertRaises(DomainError):
            self.s.increase_fixed_hours(self.normal, row['schedule_id'], 150, 120, '缺勤')


if __name__ == '__main__':
    unittest.main()
