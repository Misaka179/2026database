"""Fixed weekly catalogue and roster import against the isolated MySQL database."""
import base64
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest

from openpyxl import Workbook

import os
os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'

CORE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CORE))
from app.bootstrap import initialize_database
from app.db import Database, one
from app.fixed_slots import migrate
from app.roster import parse_workbook, TIMES
from app.service import Service, DomainError


def fixture(rows):
    book=Workbook();sheet=book.active;sheet.title='在队名单'
    sheet.append(['名单标题']);sheet.append(['姓名','学号','学院','分类'])
    for row in rows:sheet.append(row)
    stream=BytesIO();book.save(stream);book.close()
    return base64.b64encode(stream.getvalue()).decode()


class RosterParserTests(unittest.TestCase):
    def test_missing_identifier_is_skipped_with_warning(self):
        r=parse_workbook(fixture([['甲',None,'',''],['乙','00123','','周五-四时段']]))
        self.assertFalse(r['errors'])
        self.assertEqual(r['unique_students'],1)
        self.assertEqual(r['warnings'][0]['row'],3)

    def test_identifiers_optional_college_and_multiple_memberships(self):
        r=parse_workbook(fixture([['甲','00123',None,'一分队一时段'],['甲','00123',None,'周五-四时段']]))
        self.assertEqual(r['unique_students'],1)
        self.assertEqual(r['students'][0]['student_id'],'00123')
        self.assertEqual(r['students'][0]['slots'],[[1,1],[5,4]])
        self.assertFalse(r['errors'])

    def test_conflicting_names_and_formulas_are_blocked(self):
        r=parse_workbook(fixture([['甲','00123','','一分队一时段'],['乙','00123','','一分队一时段'],['丙','=123','','一分队一时段']]))
        self.assertEqual(len(r['errors']),2)

    def test_unknown_category_is_visible_not_an_invented_slot(self):
        r=parse_workbook(fixture([['甲','123','','开心花园A组']]))
        self.assertEqual(len(r['warnings']),1)
        self.assertEqual(r['memberships'],0)


class FixedRosterTests(unittest.TestCase):
    def setUp(self):
        cfg=json.loads((CORE.parent/'.work/mysql-core/admin.json').read_text(encoding='utf-8'))
        self.demo=initialize_database(cfg,database='volunteer_core_test',reset=True)
        self.settings={**cfg,'database':'volunteer_core_test'}
        migrate(self.settings,capacity=20)
        self.db=Database(self.settings)
        self.s=Service(self.db,clock=lambda:datetime(2030,1,1,8))
        self.super=self.demo['super'];self.normal=self.demo['normal']
        with self.db.transaction() as c:
            self.slot=one(c,'SELECT slot_id FROM service_slot WHERE weekday=1 AND period_no=1')['slot_id']
            self.other=one(c,'SELECT slot_id FROM service_slot WHERE weekday=2 AND period_no=1')['slot_id']
        self.s.configure_slot(self.super,self.slot,self.normal['id'],20)
        self.s.configure_slot(self.super,self.other,self.demo['other_admin']['id'],20)
        self.s.set_memberships(self.super,'20260001',[self.slot])

    def test_catalogue_is_idempotent_and_preserves_old_slots(self):
        migrate(self.settings)
        rows=self.s.list_slots(self.super)
        current=[r for r in rows if r['weekday'] is not None and r['business_code']=='CONSULT']
        self.assertEqual(len(current),35)
        self.assertEqual(len([r for r in rows if r['schedule_kind']=='LEGACY']),2)
        for r in current:
            self.assertEqual(r['team_name'][0],'周')
            self.assertEqual(str(r['start_time']),TIMES[r['period_no']-1][0].lstrip('0')+':00')
        with self.assertRaises(DomainError):
            self.s.create_slot(self.super,'非法时段',1,'10:00','11:00','图书馆',2,self.normal['id'])

    def test_date_and_membership_scope_are_enforced(self):
        self.s.create_schedule(self.normal,'20260001',self.slot,'2030-01-07')
        with self.assertRaisesRegex(DomainError,'星期'):
            self.s.create_schedule(self.super,'20260001',self.slot,'2030-01-08')
        with self.assertRaisesRegex(DomainError,'本时段队员'):
            self.s.create_schedule(self.normal,'20260002',self.slot,'2030-01-07')
        with self.assertRaises(DomainError):
            self.s.configure_slot(self.normal,self.other,self.normal['id'],20)
        self.assertEqual([r['student_id'] for r in self.s.students(self.normal)],['20260001'])
        self.assertEqual(self.s.students(self.normal,'20260002'),[])

    def test_import_previews_then_adds_accounts_once_without_overwriting(self):
        data=fixture([['导入甲','00123',None,'一分队一时段'],['导入甲','00123',None,'二分队一时段']])
        preview=self.s.import_roster(self.super,data)
        self.assertEqual(preview['new_students'],1)
        self.assertEqual(self.s.students(self.super,'00123'),[])
        result=self.s.import_roster(self.super,data,commit=True,initial_password='ImportTest123!')
        self.assertEqual(result,{'new_students':1,'existing_students':0,'added_memberships':2})
        result=self.s.import_roster(self.super,data,commit=True,initial_password='OtherPassword123!')
        self.assertEqual(result['new_students'],0);self.assertEqual(result['added_memberships'],0)
        self.s.login('student','00123','ImportTest123!')
        with self.assertRaises(DomainError):self.s.login('student','00123','OtherPassword123!')
        self.assertEqual(len(self.s.students(self.super,'00123')[0]['slots']),2)

    def test_import_error_is_atomic_and_unauthorized_import_denied(self):
        data=fixture([['甲','123','','一分队一时段'],['乙','123','','二分队一时段']])
        with self.assertRaises(DomainError):self.s.import_roster(self.normal,data)
        with self.assertRaises(DomainError):self.s.import_roster(self.super,data,commit=True,initial_password='ImportTest123!')
        self.assertEqual(self.s.students(self.super,'123'),[])

    def test_fixed_transfer_full_approval_scope_and_idempotency(self):
        student=self.demo['student']
        self.assertEqual([s['slot_id'] for s in self.s.my_memberships(student)],[self.slot])
        self.assertEqual(self.s.my_memberships(self.demo['other_student']),[])
        with self.assertRaises(DomainError):self.s.my_memberships(self.normal)
        tid=self.s.apply_fixed_transfer(student,self.slot,self.other,'调整每周时间')['transfer_id']
        self.assertEqual(len(self.s.list_applications(self.normal,'transfer')),1)
        self.assertEqual(self.s.list_applications(self.demo['other_admin'],'transfer'),())
        with self.assertRaises(DomainError):self.s.approve_transfer(self.demo['other_admin'],tid,'first',True)
        with self.assertRaises(DomainError):self.s.approve_transfer(self.super,tid,'final',True)
        self.s.approve_transfer(self.normal,tid,'first',True)
        self.s.approve_transfer(self.super,tid,'final',True)
        self.assertEqual([s['slot_id'] for s in self.s.my_memberships(student)],[self.other])
        self.assertTrue(self.s.approve_transfer(self.super,tid,'final',True)['replayed'])
        self.assertEqual(self.s.list_schedules(student),())

    def test_fixed_transfer_rechecks_capacity_and_ownership(self):
        student=self.demo['student']
        with self.assertRaises(DomainError):self.s.apply_fixed_transfer(self.demo['other_student'],self.slot,self.other,'不属于本人')
        tid=self.s.apply_fixed_transfer(student,self.slot,self.other,'每周调整')['transfer_id']
        with self.assertRaisesRegex(DomainError,'待处理'):self.s.apply_fixed_transfer(student,self.slot,self.other,'重复')
        self.s.approve_transfer(self.normal,tid,'first',True)
        self.s.configure_slot(self.super,self.other,self.demo['other_admin']['id'],1)
        self.s.set_memberships(self.super,'20260002',[self.other])
        with self.assertRaisesRegex(DomainError,'人数已满'):self.s.approve_transfer(self.super,tid,'final',True)
        self.assertEqual([s['slot_id'] for s in self.s.my_memberships(student)],[self.slot])
        self.s.set_memberships(self.super,'20260001',[])
        self.assertEqual(self.s.list_applications(student,'transfer')[0]['final_status'],'CANCELLED')

    def test_fixed_transfer_missing_configuration_and_withdrawal(self):
        with self.db.transaction(True) as c:
            c.execute('UPDATE service_slot SET need_num=NULL,manager_admin_id=NULL WHERE slot_id=%s',(self.other,))
        tid=self.s.apply_fixed_transfer(self.demo['student'],self.slot,self.other,'每周调整')['transfer_id']
        self.s.approve_transfer(self.normal,tid,'first',True)
        with self.assertRaisesRegex(DomainError,'人数上限'):self.s.approve_transfer(self.super,tid,'final',True)
        wid=self.s.apply_withdrawal(self.demo['student'],'退出')['withdrawal_id']
        self.s.approve_withdrawal(self.super,wid,True)
        self.assertEqual(self.s.list_applications(self.demo['student'],'transfer')[0]['final_status'],'CANCELLED')
        with self.assertRaises(DomainError):self.s.apply_fixed_transfer(self.demo['student'],self.slot,self.other,'已退队')

    def test_fixed_transfer_api_reads_only_self_and_rejects_forged_identity(self):
        from fastapi.testclient import TestClient
        from app.api import app,get_service,identity
        app.dependency_overrides[get_service]=lambda:self.s
        app.dependency_overrides[identity]=lambda:self.demo['student']
        try:
            with TestClient(app) as client:
                r=client.get('/my-fixed-slots')
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()[0]['slot_id'],self.slot)
                body={'old_slot_id':self.slot,'new_slot_id':self.other,'reason':'固定换班'}
                self.assertEqual(client.post('/applications/fixed-transfer',json={**body,'student_id':'20260002'}).status_code,422)
                self.assertEqual(client.post('/applications/fixed-transfer',json=body).status_code,200)
        finally:
            app.dependency_overrides.clear()
