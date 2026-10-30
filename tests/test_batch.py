import unittest
from unittest.mock import patch
import test_business
from app.service import DomainError


class BatchTests(unittest.TestCase):
    setUp=test_business.BusinessTests.setUp
    rows=test_business.BusinessTests.rows

    def collection(self,title='批量测试'):
        cid=self.s.create_collection(self.sup,self.b['干部']['business_id'],title,'2026-09-01','2026-09-06',[self.sid,'20260002'],[{'title':'工作','min_minutes':30,'max_minutes':120}])['collection_id']
        item=self.rows('SELECT item_id FROM collection_item WHERE collection_id=%s',(cid,))[0]['item_id']
        ids=[self.s.submit_hours(a,item,'2026-09-06',n)['submission_id'] for a,n in [(self.student,30),(self.demo['other_student'],90)]]
        return cid,[{'submission_id':i,'expected_revision':1} for i in ids]

    def test_batch_success_repeat_and_scope(self):
        cid,items=self.collection()
        for a in [self.normal,self.student]:
            with self.assertRaises(DomainError):self.s.approve_hours_batch(a,cid,items)
        other,_=self.collection('其他征集')
        with self.assertRaises(DomainError):self.s.approve_hours_batch(self.sup,other,items)
        result=self.s.approve_hours_batch(self.sup,cid,items,'已核验')
        self.assertEqual(result,{'approved':2,'replayed':0})
        self.assertEqual(self.s.hours(self.student)['total_minutes'],30)
        self.assertEqual(self.s.hours(self.demo['other_student'])['total_minutes'],90)
        before=self.rows('SELECT * FROM service_record');notices=self.rows('SELECT * FROM inbox_notice');logs=self.rows('SELECT * FROM operation_log')
        self.assertEqual(self.s.approve_hours_batch(self.sup,cid,items),{'approved':0,'replayed':2})
        self.assertEqual(before,self.rows('SELECT * FROM service_record'));self.assertEqual(notices,self.rows('SELECT * FROM inbox_notice'));self.assertEqual(logs,self.rows('SELECT * FROM operation_log'))

    def test_version_conflict_rolls_back_every_write_and_audit_failure(self):
        cid,items=self.collection();items[-1]['expected_revision']=9
        before={t:self.rows('SELECT * FROM '+t) for t in ('hour_submission','schedule','attendance','service_record','submission_review','operation_log','inbox_notice')}
        with self.assertRaisesRegex(DomainError,'#'+str(items[-1]['submission_id'])):self.s.approve_hours_batch(self.sup,cid,items)
        for t,rows in before.items():self.assertEqual(rows,self.rows('SELECT * FROM '+t),t)
        items[-1]['expected_revision']=1
        with patch.object(self.s,'audit',side_effect=RuntimeError('test rollback')),self.assertRaises(RuntimeError):self.s.approve_hours_batch(self.sup,cid,items)
        for t,rows in before.items():self.assertEqual(rows,self.rows('SELECT * FROM '+t),t)

    def test_first_review_required_and_mixed_replay(self):
        cid,items=self.collection();self.s.set_collection_managers(self.sup,self.normal['id'],[self.b['干部']['business_id']],'负责')
        self.s.decide_hours(self.normal,items[0]['submission_id'],True,1);items[0]['expected_revision']=2
        with self.assertRaises(DomainError):self.s.approve_hours_batch(self.sup,cid,items)
        self.assertEqual(self.s.hours(self.student)['total_minutes'],0)
        self.s.decide_hours(self.normal,items[1]['submission_id'],True,1);items[1]['expected_revision']=2
        self.s.decide_hours(self.sup,items[0]['submission_id'],True,2)
        self.assertEqual(self.s.approve_hours_batch(self.sup,cid,items),{'approved':1,'replayed':1})

    def test_read_batch_ownership_idempotency_and_all_roles(self):
        self.collection()
        for actor in [self.sup,self.normal,self.student]:
            with self.db.transaction(True) as c:
                self.s._notice(c,[(actor['kind'],actor['id'])],'batch-test-notice','TEST','测试','测试','overview')
            notices=self.s.inbox(actor)['items'];ids=[r['notice_id'] for r in notices]
            stranger=self.s.inbox(self.demo['other_student'])['items'][0]['notice_id']
            with self.assertRaises(DomainError):self.s.read_notices_batch(actor,ids+[stranger])
            self.assertTrue(all(r['read_at'] is None for r in self.s.inbox(actor)['items']))
            with self.assertRaises(DomainError):self.s.read_notices_batch(actor,ids+[999999])
            self.s.read_notices_batch(actor,ids);before=self.s.inbox(actor)['items']
            self.assertEqual(self.s.read_notices_batch(actor,ids)['updated'],0)
            self.assertEqual(before,self.s.inbox(actor)['items']);self.assertEqual(self.s.inbox(actor)['unread_count'],0)

    def test_http_contract_and_legacy_submission_bounds(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service,identity
        cid,items=self.collection();old=dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_service]=lambda:self.s;app.dependency_overrides[identity]=lambda:self.sup
            with TestClient(app) as client:
                self.assertEqual(client.post(f'/hour-collections/{cid}/approve-batch',json={'items':items}).status_code,200)
                self.assertEqual(client.post('/inbox/read-batch',json={'notice_ids':[]}).status_code,422)
                ids=[r['notice_id'] for r in self.s.inbox(self.sup)['items']]
                self.assertEqual(client.post('/inbox/read-batch',json={'notice_ids':ids}).status_code,200)
                app.dependency_overrides[identity]=lambda:self.normal
                self.assertEqual(client.post(f'/hour-collections/{cid}/approve-batch',json={'items':items}).status_code,403)
        finally:app.dependency_overrides.clear();app.dependency_overrides.update(old)
        item=self.rows('SELECT item_id FROM collection_item WHERE collection_id=%s',(cid,))[0]['item_id']
        with self.db.transaction(True) as c:
            c.execute('UPDATE hour_collection SET minute_step=1 WHERE collection_id=%s',(cid,))
            c.execute('UPDATE collection_item SET min_minutes=1,max_minutes=86 WHERE item_id=%s',(item,))
        for value in [0,15,45,90]:
            with self.assertRaises(DomainError):self.s.submit_hours(self.student,item,'2026-09-05',value)
        self.s.submit_hours(self.student,item,'2026-09-05',60)

if __name__=='__main__':unittest.main()
