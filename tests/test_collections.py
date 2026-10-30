"""Collection privacy, audience and attachment checks on the isolated test DB."""
import base64
import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile
import test_business
from app.api import app,get_service
from app.service import DomainError
from app.collection_schema import migrate
from app.collection_support import decode_attachments
from fastapi.testclient import TestClient

os.environ['VOLUNTEER_DISABLE_SCHEDULER']='1'


class CollectionTests(unittest.TestCase):
    setUp=test_business.BusinessTests.setUp
    rows=test_business.BusinessTests.rows
    term=test_business.BusinessTests.term

    def create(self,files=None):
        return self.s.create_collection(self.sup,self.b['干部']['business_id'],'测试征集','2026-09-06','2026-09-20',
            [self.sid],[{'title':'准备工作','min_minutes':60,'max_minutes':120}],files)['collection_id']

    def file(self,name='工作说明.txt',content=b'Work description'):
        return {'filename':name,'file_base64':base64.b64encode(content).decode()}

    def client(self):
        before=dict(app.dependency_overrides);app.dependency_overrides[get_service]=lambda:self.s
        def restore():app.dependency_overrides.clear();app.dependency_overrides.update(before)
        self.addCleanup(restore)
        client=TestClient(app);self.addCleanup(client.close);return client

    def auth(self,client,account,kind='admin'):
        r=client.post('/auth/login',json={'kind':kind,'account':account,'password':'TestPassword123!'})
        self.assertEqual(r.status_code,200,r.text)
        return {'Authorization':'Bearer '+r.json()['access_token']}

    def test_student_catalog_blocked_but_transfer_and_history_available(self):
        self.term([self.consult]);client=self.client();h=self.auth(client,self.sid,'student')
        self.assertEqual(client.get('/slots',headers=h).status_code,403)
        for path in ('/my-fixed-slots','/schedules','/hours'):
            self.assertEqual(client.get(path,headers=h).status_code,200)
        r=client.get('/my-transfer-options',params={'old_slot_id':self.consult},headers=h)
        self.assertEqual(r.status_code,200,r.text);rows=r.json();self.assertEqual(len(rows),34)
        self.assertTrue(all(x['business_id']==self.b['CONSULT']['business_id'] for x in rows))
        self.assertTrue(all('manager_admin_id' not in x and 'need_num' not in x for x in rows))
        self.assertEqual(client.get('/my-transfer-options',params={'old_slot_id':self.art},headers=h).status_code,403)
        target=next(x for x in rows if x['weekday']==2 and x['period_no']==1)
        r=client.post('/applications/fixed-transfer',headers=h,json={'old_slot_id':self.consult,'new_slot_id':target['slot_id'],'reason':'长期调整'})
        self.assertEqual(r.status_code,200,r.text)
        applications=client.get('/applications/transfer',headers=h).json()
        self.assertEqual(applications[0]['new_slot_name'],target['team_name'])

    def test_audience_scope_search_status_effective_dates_and_snapshot(self):
        b=self.b['干部']['business_id'];day=self.now.date().isoformat()
        self.s.set_event_member(self.sup,b,self.sid,True,day,'加入业务')
        self.s.create_student(self.sup,'001234','前导零','TestPassword123!')
        self.s.set_event_member(self.sup,b,'001234',True,'2026-09-07','未来加入')
        self.assertEqual([p['student_id'] for p in self.s.collection_participants(self.sup,b)],[self.sid])
        self.assertEqual(self.s.collection_participants(self.sup,None,'00123')[0]['student_id'],'001234')
        self.assertEqual(self.s.collection_participants(self.sup,b,'00123'),[])
        for actor in (self.normal,self.student):
            with self.assertRaises(DomainError):self.s.collection_participants(actor,b)
        cid=self.create([self.file()])
        self.s.set_event_member(self.sup,b,self.sid,False,day,'退出单项')
        self.assertEqual(self.s.collection_participants(self.sup,b),[])
        self.assertEqual(self.s.collections(self.student)[0]['collection_id'],cid)
        with self.db.transaction(True) as c:c.execute("UPDATE student SET status='DISABLED' WHERE student_id='001234'")
        self.assertEqual(self.s.collection_participants(self.sup,None,'00123'),[])

    def test_file_metadata_download_privacy_and_old_collection_compatibility(self):
        old=self.create();cid=self.create([self.file('说明.txt','内部工作说明'.encode())])
        client=self.client();sup=self.auth(client,'super');student=self.auth(client,self.sid,'student')
        listing=client.get('/hour-collections',headers=student).json()
        self.assertEqual(next(x for x in listing if x['collection_id']==old)['attachments'],[])
        f=listing[0]['attachments'][0];self.assertNotIn('content',f)
        path=f"/hour-collections/{cid}/attachments/{f['attachment_id']}"
        r=client.get(path,headers=student);self.assertEqual(r.status_code,200);self.assertEqual(r.content,'内部工作说明'.encode())
        self.assertIn('attachment;',r.headers['content-disposition']);self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertEqual(client.get(path,headers=sup).status_code,200)
        self.assertEqual(client.get(path).status_code,401)
        for h in (self.auth(client,'admin1'),self.auth(client,'20260002','student')):
            self.assertEqual(client.get(path,headers=h).status_code,403)
        logs=json.dumps(self.rows("SELECT * FROM operation_log WHERE operation_type='CREATE_COLLECTION'"),default=str)
        self.assertNotIn(self.file()['file_base64'],logs);self.assertNotIn('内部工作说明',logs)

    def test_invalid_files_atomic_rollback_and_repeat_migration(self):
        before=len(self.rows('SELECT * FROM hour_collection'))
        for f in [self.file('../a.txt'),self.file('a.exe'),self.file('fake.png'),self.file('a.txt',b''),self.file('a.txt',b'x'*(2*1024*1024+1))]:
            with self.assertRaises(DomainError):self.create([f])
        with self.assertRaises(DomainError):self.create([self.file()]*4)
        self.assertEqual(len(self.rows('SELECT * FROM hour_collection')),before)
        with patch.object(self.s,'audit',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):self.create([self.file()])
        self.assertEqual(self.rows('SELECT * FROM collection_attachment'),[])
        self.assertEqual(len(self.rows('SELECT * FROM hour_collection')),before)
        self.create([self.file()]);snapshot=self.rows('SELECT * FROM collection_attachment')
        migrate(self.settings);migrate(self.settings)
        self.assertEqual(snapshot,self.rows('SELECT * FROM collection_attachment'))

    def test_common_file_formats_and_content_mismatch(self):
        from PIL import Image
        fixtures=[self.file('说明.pdf',b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF')]
        for ext,fmt in [('png','PNG'),('jpg','JPEG')]:
            stream=BytesIO();Image.new('RGB',(2,2)).save(stream,format=fmt);fixtures.append(self.file('图片.'+ext,stream.getvalue()))
        for ext,main in [('docx','word/document.xml'),('xlsx','xl/workbook.xml')]:
            stream=BytesIO()
            with ZipFile(stream,'w') as z:z.writestr('[Content_Types].xml','<Types/>');z.writestr(main,'<document/>' if ext=='docx' else '<workbook/>')
            fixtures.append(self.file('说明.'+ext,stream.getvalue()))
        for f in fixtures:self.assertEqual(len(decode_attachments([f])),1)
        with self.assertRaises(DomainError):decode_attachments([self.file('伪装.docx',b'plain text')])
        cid=self.create([fixtures[0]])
        client=self.client();h=self.auth(client,self.sid,'student')
        attachment=self.s.collections(self.student)[0]['attachments'][0]
        r=client.get(f"/hour-collections/{cid}/attachments/{attachment['attachment_id']}?preview=true",headers=h)
        self.assertEqual(r.status_code,200);self.assertTrue(r.headers['content-disposition'].startswith('inline;'))


if __name__=='__main__':unittest.main()
