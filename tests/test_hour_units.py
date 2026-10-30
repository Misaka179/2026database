import unittest
from unittest.mock import patch
import test_business
from app.service import DomainError
from app.hour_units import migrate


class HalfHourTests(unittest.TestCase):
    setUp=test_business.BusinessTests.setUp
    rows=test_business.BusinessTests.rows

    def collection(self,low=30,high=120):
        result=self.s.create_collection(self.sup,self.b['干部']['business_id'],'半小时规则','2026-09-01','2026-09-06',[self.sid],[{'title':'工作','min_minutes':low,'max_minutes':high}])
        return self.rows('SELECT * FROM collection_item WHERE collection_id=%s',(result['collection_id'],))[0]

    def test_bounds_reject_fractional_steps_and_rollback(self):
        for low,high in [(0,60),(15,60),(30,45),(60,30),(30,1470),(30,60.5)]:
            with self.subTest(low=low,high=high),self.assertRaises(DomainError):self.collection(low,high)
        self.assertEqual(self.rows('SELECT * FROM hour_collection'),[])
        self.collection(30,1440)

    def test_submission_review_and_manual_edit_enforce_same_unit(self):
        item=self.collection()
        for amount in (0,15,45,150,30.5):
            with self.subTest(amount=amount),self.assertRaises(DomainError):self.s.submit_hours(self.student,item['item_id'],'2026-09-06',amount)
        sid=self.s.submit_hours(self.student,item['item_id'],'2026-09-06',90)['submission_id']
        self.s.decide_hours(self.sup,sid,True,1)
        record=self.s.hours(self.student)['records'][0];self.assertEqual(record['minute_step'],30)
        for amount in (0,45,75):
            with self.assertRaises(DomainError):self.s.correct_hours_review(self.sup,sid,True,2,'核实',amount)
            with self.assertRaises(DomainError):self.s.revise_hours(self.sup,record['record_id'],amount,'核实')
        self.s.revise_hours(self.sup,record['record_id'],60,'核实')
        self.s.correct_hours_review(self.sup,sid,False,2,'撤销错误认定')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)

    def test_legacy_values_survive_migration_and_remain_editable(self):
        item=self.collection()
        with self.db.transaction(True) as c:
            c.execute('UPDATE hour_collection SET minute_step=1 WHERE collection_id=%s',(item['collection_id'],))
            c.execute('UPDATE collection_item SET min_minutes=1,max_minutes=125 WHERE item_id=%s',(item['item_id'],))
        migrate(self.settings);migrate(self.settings)
        with self.assertRaises(DomainError):self.s.submit_hours(self.student,item['item_id'],'2026-09-06',47)
        # Existing pre-upgrade submission remains untouched; only new submissions use half hours.
        with self.db.transaction(True) as c:
            c.execute("INSERT INTO hour_submission(item_id,student_id,service_date,service_minutes,remark) VALUES(%s,%s,%s,47,'历史记录')",(item['item_id'],self.sid,'2026-09-06'))
            sid=c.lastrowid
        self.s.decide_hours(self.sup,sid,True,1)
        self.s.correct_hours_review(self.sup,sid,True,2,'历史规则',49)
        record=self.s.hours(self.student)['records'][0]
        self.s.revise_hours(self.sup,record['record_id'],51,'历史规则')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],51)
        self.assertEqual(self.rows('SELECT min_minutes,max_minutes FROM collection_item')[0],{'min_minutes':1,'max_minutes':125})

    def test_non_collection_records_keep_minute_precision(self):
        event=self.s.create_event(self.sup,'独立专项',self.sid,'工作','2026-09-06',47,'核实','test-event-half-hour')
        record=self.s.hours(self.student)['records'][0]
        self.s.revise_hours(self.sup,record['record_id'],49,'核实')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],49)

if __name__=='__main__':unittest.main()
