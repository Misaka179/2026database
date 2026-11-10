"""统一 Excel 导入：本班次锁定、待确认默认跳过、撤销批次。"""
import unittest

import test_business
from app.service import DomainError
from test_roster import fixture


class UnifiedImportTests(unittest.TestCase):
    setUp = test_business.BusinessTests.setUp
    rows = test_business.BusinessTests.rows

    def test_slot_scope_pins_every_row_to_the_current_slot(self):
        # 「分类」列留空，三级页传 slot_id 后不再依赖分类识别
        book = fixture([['甲', '0012300000001', '', ''],
                        ['乙', '0012300000002', '', '一分队五时段']])
        preview = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'],
                                       slot_id=self.art)
        self.assertEqual(preview['target_slot']['slot_id'], self.art)
        self.assertFalse(preview['errors'])
        self.assertEqual(preview['memberships'], 2)
        result = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'],
                                      slot_id=self.art, commit=True, initial_password='ImportTest123!')
        self.assertEqual(result['added_memberships'], 2)
        for sid in ('0012300000001', '0012300000002'):
            with self.db.transaction() as c:
                from app.db import all_rows
                slots = [r['slot_id'] for r in all_rows(
                    c, 'SELECT slot_id FROM slot_member WHERE student_id=%s', (sid,))]
            self.assertEqual(slots, [self.art])
        self.assertGreater(self.s.member_import_list(self.sup, self.b['ART']['business_id'])['batches'][0]['batch_id'], 0)

    def test_name_mismatch_is_pending_and_approved_import_keeps_stored_name(self):
        book = fixture([['张三改', self.sid, '', '一分队三时段']])
        preview = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'])
        self.assertEqual([p['issue'] for p in preview['pending']], ['name'])
        with self.assertRaises(DomainError):
            self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'], commit=True)
        result = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'],
                                      approvals={self.sid: True}, commit=True,
                                      initial_password='ImportTest123!')
        self.assertEqual(result['added_memberships'], 1)
        self.assertEqual(self.rows('SELECT name FROM student WHERE student_id=%s', (self.sid,))[0]['name'], '张三')

    def test_credit_disabled_account_is_skipped_not_pending(self):
        with self.db.transaction(True) as c:
            c.execute("UPDATE student SET disabled_by_credit=1,status='DISABLED' WHERE student_id=%s", (self.sid,))
        book = fixture([['张三', self.sid, '', '一分队三时段']])
        preview = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'])
        self.assertEqual(preview['pending'], [])
        self.assertEqual(len(preview['credits']), 1)
        with self.assertRaises(DomainError):
            self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'], commit=True)

    def test_member_import_refuses_business_scope_when_groups_exist(self):
        bid = self.b['干部']['business_id']
        encoded = self._member_book([['甲', '0012300000003', '测试学院']])
        with self.assertRaisesRegex(DomainError, '小组'):
            self.s.import_members(self.sup, encoded, mappings={'综运': {'business_id': bid, 'group_id': None}})

    def test_conflicting_slot_approved_then_revert_restores_previous(self):
        # 已在咨询服务一时段，再导入美育同时段：咨询与美育互斥，属于时段冲突
        self.s.set_memberships(self.sup, self.sid, [self.consult])
        book = fixture([['张三', self.sid, '', '一分队三时段']])
        preview = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'])
        self.assertEqual([p['issue'] for p in preview['pending']], ['slot'])
        result = self.s.import_roster(self.sup, book, business_id=self.b['ART']['business_id'],
                                      approvals={self.sid: True}, commit=True,
                                      initial_password='ImportTest123!')
        self.assertEqual([s['slot_id'] for s in self.s.my_memberships(self.student)], [self.art])
        revert = self.s.revert_member_import(self.sup, result['batch_id'])
        self.assertEqual(revert['restored_slots'], 1)
        self.assertEqual([s['slot_id'] for s in self.s.my_memberships(self.student)], [self.consult])
        with self.assertRaises(DomainError):
            self.s.revert_member_import(self.sup, result['batch_id'])

    def test_member_import_commit_writes_scope_and_revert_keeps_history(self):
        bid = self.b['干部']['business_id']
        gid = self.rows('SELECT group_id FROM business_group WHERE business_id=%s ORDER BY group_id LIMIT 1', (bid,))[0]['group_id']
        encoded = self._member_book([['甲', '0012300000004', '测试学院']])
        result = self.s.import_members(self.sup, encoded, scope={'business_id': bid, 'group_id': gid},
                                      commit=True, initial_password='ImportTest123!')
        self.assertGreater(result['batch_id'], 0)
        batch = self.s.member_import_batch(self.sup, result['batch_id'])
        self.assertEqual(batch['scope_kind'], 'GROUP')
        self.assertEqual(batch['scope_id'], gid)
        revert = self.s.revert_member_import(self.sup, result['batch_id'])
        self.assertEqual(revert['removed_memberships'], 1)
        self.assertEqual(self.rows('SELECT 1 AS n FROM group_member WHERE group_id=%s AND student_id=%s',
                                   (gid, '0012300000004')), [])

    def _member_book(self, rows):
        import base64
        from io import BytesIO
        from openpyxl import Workbook
        book = Workbook(); sheet = book.active; sheet.title = '综运'
        sheet.append(['姓名', '学号', '学院'])
        for row in rows:
            sheet.append(row)
        data = BytesIO(); book.save(data); book.close()
        return base64.b64encode(data.getvalue()).decode()


if __name__ == '__main__':
    unittest.main()
