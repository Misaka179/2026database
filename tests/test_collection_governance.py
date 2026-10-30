"""Three roles, two-stage accounting, private claim files and inbox events."""
import base64
from datetime import datetime
import unittest
from unittest.mock import patch
import test_business
from app.service import DomainError


class GovernanceTests(unittest.TestCase):
    setUp=test_business.BusinessTests.setUp
    rows=test_business.BusinessTests.rows
    term=test_business.BusinessTests.term

    def grant(self):
        bid=self.b['干部']['business_id']
        self.s.set_collection_managers(self.sup,self.normal['id'],[bid],'负责该业务征集')
        self.s.set_event_member(self.sup,bid,self.sid,True,'2026-09-06','加入业务')
        return bid

    def create(self,actor=None,deadline='2026-09-30',end='2026-09-20'):
        cid=self.s.create_collection(actor or self.normal,self.b['干部']['business_id'],'三级审批','2026-09-06',end,[self.sid],
            [{'title':'资料整理','min_minutes':60,'max_minutes':120}],submission_deadline=deadline)['collection_id']
        item=self.rows('SELECT item_id FROM collection_item WHERE collection_id=%s',(cid,))[0]['item_id']
        return cid,item

    def file(self,text='工作证明'):
        return {'filename':'工作说明.txt','file_base64':base64.b64encode(text.encode()).decode()}

    def test_scope_application_review_revoke_and_participant_boundaries(self):
        bid=self.b['干部']['business_id'];otherbid=self.b['讲解队']['business_id']
        req=self.s.request_collection_scope(self.normal,[bid],'负责活动')['request_ids'][0]
        self.assertEqual(self.s.request_collection_scope(self.normal,[bid],'重复')['request_ids'],[req])
        with self.assertRaises(DomainError):self.s.collection_participants(self.normal,bid)
        self.s.decide_collection_scope(self.sup,req,True,1)
        self.assertTrue(self.s.decide_collection_scope(self.sup,req,True,1)['replayed'])
        self.s.set_event_member(self.sup,bid,self.sid,True,'2026-09-06','加入')
        self.assertEqual(len(self.s.collection_participants(self.normal)),1)
        with self.assertRaises(DomainError):self.s.collection_participants(self.normal,otherbid)
        self.create()
        with self.assertRaises(DomainError):self.s.create_collection(self.normal,bid,'越权','2026-09-06','2026-09-07',['20260002'],[{'title':'事项','min_minutes':0,'max_minutes':60}])
        self.s.set_collection_managers(self.sup,self.normal['id'],[],'结束授权')
        self.assertEqual(self.s.collections(self.normal),[])
        with self.assertRaises(DomainError):self.create()
        with self.assertRaises(DomainError):self.s.set_collection_managers(self.normal,self.other['id'],[bid],'越权')

    def test_two_stage_minutes_corrections_and_retries(self):
        self.grant();cid,item=self.create()
        sub=self.s.submit_hours(self.student,item,'2026-09-06',60,attachments=[self.file()])['submission_id']
        with self.assertRaises(DomainError):self.s.decide_hours(self.sup,sub,True,1)
        with self.assertRaises(DomainError):self.s.decide_hours(self.other,sub,True,1)
        self.assertEqual(self.s.decide_hours(self.normal,sub,True,1)['status'],'FIRST_APPROVED')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.assertTrue(self.s.decide_hours(self.normal,sub,True,1)['replayed'])
        self.s.decide_hours(self.sup,sub,True,2)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],60)
        self.s.correct_hours_review(self.sup,sub,True,3,'核对实际工作',90)
        self.assertTrue(self.s.correct_hours_review(self.sup,sub,True,3,'核对实际工作',90)['replayed'])
        self.assertEqual(self.s.hours(self.student)['total_minutes'],90)
        self.s.correct_hours_review(self.sup,sub,False,4,'材料存在问题')
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.s.correct_hours_review(self.sup,sub,True,5,'核验无误',90)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],90)
        self.assertEqual(len(self.rows('SELECT * FROM service_record')),1)
        self.assertEqual(self.s.credit(self.student)['credit_score'],5)
        self.assertEqual(len(self.rows('SELECT * FROM submission_review')),5)

    def test_submission_files_privacy_replacement_and_history(self):
        self.grant();cid,item=self.create();f=self.file()
        sub=self.s.submit_hours(self.student,item,'2026-09-06',60,attachments=[f])['submission_id']
        self.assertTrue(self.s.submit_hours(self.student,item,'2026-09-06',60,attachments=[f])['replayed'])
        attachment=self.s.collections(self.student)[0]['submissions'][0]['attachments'][0]
        for a in (self.student,self.normal,self.sup):self.assertEqual(self.s.submission_attachment(a,sub,attachment['attachment_id'])['content'],'工作证明'.encode())
        for a in (self.other,{'kind':'student','id':'20260002'}):
            with self.assertRaises(DomainError):self.s.submission_attachment(a,sub,attachment['attachment_id'])
        self.s.decide_hours(self.normal,sub,False,1,'补充说明')
        self.s.submit_hours(self.student,item,'2026-09-06',90,'更新说明',2,attachments=[])
        current=self.s.collections(self.student)[0]['submissions'][0]
        self.assertEqual(list(current['attachments']),[])
        self.assertEqual(len(self.rows('SELECT * FROM submission_attachment')),1)
        self.assertEqual(current['revision'],3)
        with self.assertRaises(DomainError):self.s.correct_hours_review(self.normal,sub,True,3,'越权',90)

    def test_restoring_rejected_claim_after_another_event_reuses_its_slot(self):
        self.grant();cid,item=self.create()
        sub=self.s.submit_hours(self.student,item,'2026-09-06',60)['submission_id']
        self.s.decide_hours(self.normal,sub,True,1)
        original=self.s.decide_hours(self.sup,sub,True,2)['schedule_id']
        self.s.correct_hours_review(self.sup,sub,False,3,'待补充材料')
        self.s.create_event(self.sup,'干部',self.sid,'资料整理','2026-09-06',30,'另一次独立工作','restore-collision-test')
        restored=self.s.correct_hours_review(self.sup,sub,True,4,'材料已核实',60)
        self.assertEqual(restored['schedule_id'],original)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],90)
        self.assertEqual(len(self.rows('SELECT * FROM service_record')),2)

    def test_deadline_manual_close_notifications_and_review_after_close(self):
        self.grant();cid,item=self.create(deadline='2026-09-10',end='2026-09-07');self.now=datetime(2026,9,10,23,59)
        sub=self.s.submit_hours(self.student,item,'2026-09-07',60)['submission_id']
        self.now=datetime(2026,9,11)
        self.assertEqual(self.s.run_collection_deadlines()['closed'],1)
        self.assertEqual(self.s.run_collection_deadlines()['closed'],0)
        with self.assertRaises(DomainError):self.s.submit_hours(self.student,item,'2026-09-06',60)
        self.s.decide_hours(self.normal,sub,True,1);self.s.decide_hours(self.sup,sub,True,2)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],60)
        notices=self.rows("SELECT * FROM inbox_notice WHERE event_key=%s",(f'collection-closed:{cid}',))
        self.assertEqual(len(notices),3)
        cid2,item2=self.create();self.s.close_collection(self.normal,cid2,'活动提前结束')
        self.assertTrue(self.s.close_collection(self.normal,cid2,'重试')['replayed'])
        with self.assertRaises(DomainError):self.s.submit_hours(self.student,item2,'2026-09-07',60)

    def test_inbox_privacy_read_state_and_transaction_rollback(self):
        self.grant();cid,item=self.create();student=self.s.inbox(self.student)
        self.assertEqual(student['unread_count'],1)
        notice=student['items'][0]['notice_id']
        with self.assertRaises(DomainError):self.s.read_notice(self.normal,notice)
        self.s.read_notice(self.normal)
        self.assertEqual(self.s.inbox(self.student)['unread_count'],1)
        self.s.read_notice(self.student,notice);self.assertEqual(self.s.inbox(self.student)['unread_count'],0)
        count=len(self.rows('SELECT * FROM inbox_notice'))
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.create()
        self.assertEqual(len(self.rows('SELECT * FROM inbox_notice')),count)
        self.s.apply_withdrawal(self.student,'退出队伍')
        self.assertTrue(any('退队' in r['title'] for r in self.s.inbox(self.sup)['items']))


if __name__=='__main__':unittest.main()
