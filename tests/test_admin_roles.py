"""Administrator grants and scoped test accounts in isolated MySQL only."""
import json
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_semester as fixtures
from app.db import one
from app.service import DomainError
from app.security import hash_password
from app.admin_roles import migrate
from scripts.setup_test_admins import provision


class AdministratorTests(unittest.TestCase):
    setUp = fixtures.SemesterTests.setUp
    rows = fixtures.SemesterTests.rows
    term = fixtures.SemesterTests.term

    def promote(self, slots=()):
        return self.s.promote_student(self.super,self.student['id'],'指定时段负责人',slots)

    def test_grant_preserves_volunteer_and_hours_and_has_exact_scope(self):
        self.term()
        before=self.rows('SELECT * FROM student WHERE student_id=%s',(self.student['id'],))[0]
        members=self.rows('SELECT * FROM slot_member ORDER BY slot_id')
        schedules=self.s.list_schedules(self.student)
        result=self.promote([self.mon])
        manager=self.s.login('admin',self.student['id'],'TestPassword123!')
        self.assertEqual(manager['id'],result['admin_id'])
        self.assertEqual(self.s.me(manager)['role'],'NORMAL')
        self.assertEqual(self.s.login('student',self.student['id'],'TestPassword123!'),self.student)
        self.assertEqual(before,self.rows('SELECT * FROM student WHERE student_id=%s',(self.student['id'],))[0])
        self.assertEqual(members,self.rows('SELECT * FROM slot_member ORDER BY slot_id'))
        self.assertEqual(len(schedules),len(self.s.list_schedules(self.student)))
        self.assertEqual({r['slot_id'] for r in self.s.list_schedules(manager)},{self.mon})
        self.assertNotIn('password_hash',self.s.me(manager))
        with self.assertRaises(DomainError):self.s.configure_slot(manager,self.tue,result['admin_id'],20)
        with self.assertRaises(DomainError):self.s.set_student_credit(manager,self.student['id'],10,1,'无权调分')
        logs=self.rows("SELECT * FROM operation_log WHERE operation_type='PROMOTE_STUDENT'")
        self.assertNotIn('password',json.dumps(logs,default=str))

    def test_only_super_may_grant_and_only_active_student(self):
        for actor in (self.normal,self.student):
            with self.assertRaises(DomainError) as error:self.s.promote_student(actor,self.student['id'],'授权',[])
            self.assertEqual(error.exception.status,403)
        with self.assertRaises(DomainError):self.s.promote_student(self.super,'missing','授权',[])
        with self.assertRaises(DomainError):self.s.promote_student(self.super,self.student['id'],' ',[])
        for status in ('QUIT','DISABLED'):
            with self.db.transaction(True) as c:c.execute('UPDATE student SET status=%s WHERE student_id=%s',(status,self.student['id']))
            with self.assertRaises(DomainError):self.promote()

    def test_duplicate_concurrent_grants_create_one_identity_and_audit(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.promote([self.mon]),range(2)))
        self.assertEqual(results[0]['admin_id'],results[1]['admin_id'])
        self.assertEqual(sum(r['replayed'] for r in results),1)
        self.assertEqual(len(self.rows("SELECT * FROM operation_log WHERE operation_type='PROMOTE_STUDENT'")),1)

    def test_account_collision_and_bad_slot_never_take_over_existing_account(self):
        occupied=self.s.create_admin(self.super,'独立账户',self.student['id'],'TestPassword123!')['admin_id']
        with self.assertRaisesRegex(DomainError,'占用'):self.promote([self.mon])
        self.assertIsNone(self.rows('SELECT student_id FROM admin WHERE admin_id=%s',(occupied,))[0]['student_id'])
        with self.assertRaises(DomainError):self.s.promote_student(self.super,self.demo['other_student']['id'],'授权',[self.mon,999999])
        self.assertFalse(self.rows('SELECT * FROM admin WHERE student_id IS NOT NULL'))

    def test_audit_failure_rolls_back_grant_and_assignment(self):
        with patch.object(self.s,'audit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.promote([self.mon])
        self.assertFalse(self.rows('SELECT * FROM admin WHERE student_id IS NOT NULL'))
        self.assertEqual(self.rows('SELECT manager_admin_id FROM service_slot WHERE slot_id=%s',(self.mon,))[0]['manager_admin_id'],self.normal['id'])

    def test_linked_login_uses_current_student_credentials_and_checks_status(self):
        result=self.promote()
        actor={'kind':'admin','id':result['admin_id']}
        with self.db.transaction(True) as c:c.execute('UPDATE student SET password_hash=%s WHERE student_id=%s',(hash_password('ChangedTest123!'),self.student['id']))
        with self.assertRaises(DomainError):self.s.login('admin',self.student['id'],'TestPassword123!')
        self.assertEqual(self.s.login('admin',self.student['id'],'ChangedTest123!'),actor)
        for status in ('DISABLED','QUIT'):
            with self.db.transaction(True) as c:c.execute('UPDATE student SET status=%s WHERE student_id=%s',(status,self.student['id']))
            with self.assertRaises(DomainError):self.s.me(actor)
            with self.assertRaises(DomainError):self.s.login('admin',self.student['id'],'ChangedTest123!')

    def test_manager_can_be_set_without_inventing_capacity(self):
        self.term()
        self.s.configure_slot(self.super,self.mon,self.normal['id'],None)
        result=self.promote([self.mon])
        slot=self.rows('SELECT * FROM service_slot WHERE slot_id=%s',(self.mon,))[0]
        self.assertIsNone(slot['need_num'])
        self.assertEqual(slot['manager_admin_id'],result['admin_id'])
        with self.assertRaises(DomainError):self.s.configure_slot(self.super,self.mon,result['admin_id'],0)

    def test_existing_admin_migration_preserves_data_and_is_repeatable(self):
        with self.db.transaction(True) as c:
            c.execute('ALTER TABLE admin DROP FOREIGN KEY fk_admin_student,DROP INDEX uq_admin_student,DROP COLUMN student_id')
        before=self.rows('SELECT admin_id,name,account,password_hash,role,status FROM admin')
        migrate(self.settings);migrate(self.settings)
        self.assertEqual(before,self.rows('SELECT admin_id,name,account,password_hash,role,status FROM admin'))
        self.promote()

    def test_http_grant_roles_validation_and_login(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service
        old=dict(app.dependency_overrides)
        app.dependency_overrides[get_service]=lambda:self.s
        self.addCleanup(lambda:(app.dependency_overrides.clear(),app.dependency_overrides.update(old)))
        with TestClient(app) as client:
            def headers(account):
                r=client.post('/auth/login',json={'kind':'admin','account':account,'password':'TestPassword123!'})
                return {'Authorization':'Bearer '+r.json()['access_token']}
            payload={'reason':'队员管理授权','slot_ids':[self.mon]}
            url=f"/students/{self.student['id']}/administrator"
            self.assertEqual(client.post(url,json=payload).status_code,401)
            self.assertEqual(client.post(url,headers=headers('admin1'),json=payload).status_code,403)
            super_headers=headers('super')
            self.assertEqual(client.post(url,headers=super_headers,json={**payload,'role':'SUPER'}).status_code,422)
            self.assertEqual(client.post(url,headers=super_headers,json=payload).status_code,200)
            result=client.get('/admins',headers=super_headers).json()
            self.assertTrue(any(a['student_id']==self.student['id'] for a in result))
            self.assertNotIn('password',json.dumps(result))
            self.assertEqual(client.get('/auth/me',headers=headers(self.student['id'])).json()['role'],'NORMAL')

    def test_test_accounts_are_scoped_idempotent_and_preserve_existing_managers(self):
        slots=self.rows('SELECT slot_id,weekday,period_no FROM service_slot WHERE weekday IS NOT NULL AND business_id=(SELECT business_id FROM business WHERE code=\'CONSULT\')')
        accounts=[{**s,'account':f"test_w{s['weekday']}_p{s['period_no']}",'password':'TestPassword123!'} for s in slots]
        r=provision(self.s,self.super,accounts)
        self.assertEqual(r,{'created':35,'assigned':31,'preserved':4})
        self.assertEqual(provision(self.s,self.super,accounts),{'created':0,'assigned':0,'preserved':4})
        actor=self.s.login('admin','test_w5_p4','TestPassword123!')
        assigned=self.rows('SELECT * FROM service_slot WHERE manager_admin_id=%s',(actor['id'],))
        self.assertEqual([(s['weekday'],s['period_no']) for s in assigned],[(5,4)])
        self.assertIsNone(assigned[0]['need_num'])
        with self.assertRaises(DomainError):provision(self.s,self.normal,accounts)
