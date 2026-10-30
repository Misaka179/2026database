"""HTTP integration tests against the separately named disposable MySQL test DB.

Run with the other tests using unittest's serial discovery. Do not run this
module concurrently with another process using volunteer_core_test: each test
deliberately resets that database. No main-database data is modified.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import os
os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'

CORE = Path(__file__).resolve().parents[1]
WORKSPACE = CORE.parent
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(WORKSPACE / ".work" / "python-packages"))

from fastapi.testclient import TestClient
from app.api import app, get_service
from app.bootstrap import initialize_database
from app.db import Database
from app.service import Service


class APIIntegrationTests(unittest.TestCase):
    """Use real SQL and real authentication, replacing only the clock/settings."""

    @classmethod
    def setUpClass(cls):
        state = WORKSPACE / ".work" / "mysql-core"
        cls.admin_settings = json.loads((state / "admin.json").read_text(encoding="utf-8"))
        runtime = json.loads((state / "runtime.json").read_text(encoding="utf-8"))
        cls.runtime_settings = {**runtime, "database": "volunteer_core_test"}

    def setUp(self):
        self.seed = initialize_database(
            self.admin_settings, database="volunteer_core_test", demo=True, reset=True
        )
        self.service = Service(
            Database(self.runtime_settings), clock=lambda: datetime(2030, 1, 1, 0, 0)
        )
        environment = patch.dict(
            os.environ,
            {"VOLUNTEER_TOKEN_SECRET": "api-integration-test-only-fixed-key-not-for-production"},
        )
        environment.start()
        self.addCleanup(environment.stop)
        original_overrides = dict(app.dependency_overrides)
        self.addCleanup(self.restore_overrides, original_overrides)
        app.dependency_overrides[get_service] = lambda: self.service
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers_by_account = {}

    @staticmethod
    def restore_overrides(original):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)

    def check(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def headers(self, account="20260001", kind=None):
        kind = kind or ("student" if account.startswith("2026") else "admin")
        key = (kind, account)
        if key not in self.headers_by_account:
            result = self.check(self.client.post("/auth/login", json={
                "kind": kind, "account": account, "password": "TestPassword123!"
            }))
            self.assertEqual(result["token_type"], "bearer")
            self.headers_by_account[key] = {"Authorization": "Bearer " + result["access_token"]}
        return self.headers_by_account[key]

    def slot_body(self):
        return {
            "team_name": "API测试分队", "period_no": 2,
            "start_time": "16:00", "end_time": "18:00",
            "location": "图书馆二楼", "need_num": 2,
            "manager_admin_id": self.seed["normal"]["id"],
        }

    def create_schedule(self, student_id="20260001", day="2030-01-02"):
        return self.check(self.client.post("/schedules", headers=self.headers("admin1"), json={
            "student_id": student_id, "slot_id": self.seed["slot"], "schedule_date": day
        }))["schedule_id"]

    def create_transfer(self):
        from app.fixed_slots import migrate
        from app.db import one
        old_id=self.create_schedule()
        migrate({**self.admin_settings,'database':'volunteer_core_test'})
        with self.service.db.transaction() as c:
            old=one(c,'SELECT slot_id FROM service_slot WHERE weekday=1 AND period_no=1')['slot_id']
            target=one(c,'SELECT slot_id FROM service_slot WHERE weekday=2 AND period_no=1')['slot_id']
        self.service.configure_slot(self.seed['super'],old,self.seed['normal']['id'],20)
        self.service.configure_slot(self.seed['super'],target,self.seed['other_admin']['id'],20)
        self.service.set_memberships(self.seed['super'],'20260001',[old])
        transfer_id=self.check(self.client.post('/applications/fixed-transfer',headers=self.headers(),json={'old_slot_id':old,'new_slot_id':target,'reason':'长期换时段'}))['transfer_id']
        return old_id,transfer_id

    def test_missing_token_is_rejected(self):
        for path in ("/auth/me", "/hours", "/slots", "/schedules", "/applications/transfer"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.check(response, 401)
                self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
        self.check(self.client.post("/slots", json=self.slot_body()), 401)

    def test_login_identity_and_incorrect_password(self):
        student = self.check(self.client.get("/auth/me", headers=self.headers()))
        self.assertEqual(student["student_id"], "20260001")
        self.assertEqual(student["credit_score"], 5)
        self.assertNotIn("password_hash", student)
        self.assertNotIn("password", student)
        administrator = self.check(self.client.get("/auth/me", headers=self.headers("super")))
        self.assertEqual(administrator["role"], "SUPER")
        self.assertNotIn("password_hash", administrator)
        for kind, account in (("student", "20260001"), ("admin", "super"), ("student", "unknown")):
            with self.subTest(kind=kind, account=account):
                self.check(self.client.post("/auth/login", json={
                    "kind": kind, "account": account, "password": "IncorrectPassword!"
                }), 401)

    def test_forged_identity_and_malformed_tokens_are_rejected(self):
        token = self.headers()["Authorization"].removeprefix("Bearer ")
        body, signature = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        payload.update(kind="admin", id=str(self.seed["super"]["id"]))
        forged_body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()
        for forged in (forged_body + "." + signature, "not-a-token", body + "." + "0" * 64):
            with self.subTest(forgery=forged[:16]):
                self.check(self.client.get("/auth/me", headers={"Authorization": "Bearer " + forged}), 401)
        self.check(self.client.get("/auth/me", headers=self.headers()))

    def test_student_cannot_read_other_hours_or_create_scheduling_data(self):
        own = self.check(self.client.get("/hours", headers=self.headers()))
        self.assertEqual(own["student_id"], "20260001")
        self.assertEqual(own["total_minutes"], 0)
        self.check(self.client.get("/hours?student_id=20260002", headers=self.headers()), 403)
        self.check(self.client.get("/credit?student_id=20260002", headers=self.headers()), 403)
        self.check(self.client.post("/slots", headers=self.headers(), json=self.slot_body()), 403)
        self.check(self.client.post("/schedules", headers=self.headers(), json={
            "student_id": "20260001", "slot_id": self.seed["slot"], "schedule_date": "2030-01-02"
        }), 403)
        self.check(self.client.get("/slots", headers=self.headers()), 403)
        self.assertEqual(self.check(self.client.get("/schedules", headers=self.headers())), [])

    def test_student_cannot_apply_for_another_students_schedule(self):
        other_id = self.create_schedule(student_id="20260002")
        self.check(self.client.post("/applications/leave", headers=self.headers(), json={
            "schedule_id": other_id, "reason": "尝试代替他人请假"
        }), 403)
        self.check(self.client.post("/applications/transfer", headers=self.headers(), json={
            "old_schedule_id": other_id, "new_slot_id": self.seed["other_slot"],
            "new_date": "2030-01-03", "reason": "尝试修改他人排班"
        }), 410)
        self.assertEqual(self.check(self.client.get("/applications/leave", headers=self.headers())), [])
        self.assertEqual(self.check(self.client.get("/applications/transfer", headers=self.headers())), [])

    def test_normal_admin_cannot_final_approve_or_change_credit_rule(self):
        old_id, transfer_id = self.create_transfer()
        self.check(self.client.post(
            f"/applications/transfer/{transfer_id}/first", headers=self.headers("admin1"),
            json={"approved": True}
        ))
        self.check(self.client.post(
            f"/applications/transfer/{transfer_id}/final", headers=self.headers("admin1"),
            json={"approved": True}
        ), 403)
        self.check(self.client.put("/credit-rules/LATE", headers=self.headers("admin1"), json={
            "deduct_score": 1, "reason": "普通管理员尝试修改信用规则"
        }), 403)
        applications = self.check(self.client.get("/applications/transfer", headers=self.headers()))
        self.assertEqual(applications[0]["final_status"], "PENDING")
        schedules = self.check(self.client.get("/schedules", headers=self.headers()))
        self.assertEqual([(row["schedule_id"], row["status"]) for row in schedules], [(old_id, "ACTIVE")])
        rules = self.check(self.client.get("/credit-rules", headers=self.headers("super")))
        self.assertEqual(len([r for r in rules if r['status']=='ACTIVE']), 2)
        self.assertEqual(next(row for row in rules if row["violation_type"] == "LATE")["deduct_score"], 2)

    def test_fixed_transfer_requires_two_stages_and_updates_membership(self):
        old_id,tid=self.create_transfer()
        final_path=f'/applications/transfer/{tid}/final'
        self.check(self.client.post(final_path,headers=self.headers('super'),json={'approved':True}),409)
        self.check(self.client.post(f'/applications/transfer/{tid}/first',headers=self.headers('admin1'),json={'approved':True}))
        result=self.check(self.client.post(final_path,headers=self.headers('super'),json={'approved':True}))
        self.assertTrue(result['fixed_membership_updated'])
        members=self.check(self.client.get('/my-fixed-slots',headers=self.headers()))
        self.assertEqual([r['weekday'] for r in members],[2])
        self.assertTrue(self.check(self.client.post(final_path,headers=self.headers('super'),json={'approved':True}))['replayed'])
        self.assertEqual(len(self.check(self.client.get('/schedules',headers=self.headers()))),1)

    def test_invalid_dates_and_extra_actor_fields_are_rejected(self):
        valid = {"student_id": "20260001", "slot_id": self.seed["slot"], "schedule_date": "2030-01-02"}
        invalid_payloads = [
            {**valid, "schedule_date": "2030-02-30"},
            {**valid, "schedule_date": "not-a-date"},
            {**valid, "actor": {"kind": "admin", "id": self.seed["super"]["id"]}},
            {**valid, "role": "SUPER"},
            {**valid, "admin_id": self.seed["super"]["id"]},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.check(self.client.post("/schedules", headers=self.headers("admin1"), json=payload), 422)
        self.check(self.client.post("/auth/login", json={
            "kind": "student", "account": "20260001", "password": "TestPassword123!", "role": "SUPER"
        }), 422)
        self.check(self.client.post("/slots", headers=self.headers("super"), json={
            **self.slot_body(), "start_time": "25:00"
        }), 422)
        self.assertEqual(self.check(self.client.get("/schedules", headers=self.headers("admin1"))), [])

    def test_mysql_times_are_human_readable_json_strings(self):
        slots = self.check(self.client.get("/slots", headers=self.headers("super")))
        indexed = {slot["slot_id"]: slot for slot in slots}
        self.assertEqual(indexed[self.seed["slot"]]["start_time"], "10:00")
        self.assertEqual(indexed[self.seed["slot"]]["end_time"], "12:00")
        self.assertEqual(indexed[self.seed["other_slot"]]["start_time"], "14:00")
        for slot in slots:
            self.assertIsInstance(slot["start_time"], str)
            self.assertIsInstance(slot["end_time"], str)
            self.assertRegex(slot["start_time"], r"^\d{2}:\d{2}$")
        schedule_id = self.create_schedule()
        schedules = self.check(self.client.get("/schedules", headers=self.headers()))
        self.assertEqual(schedules[0]["schedule_id"], schedule_id)
        self.assertEqual(schedules[0]["schedule_date"], "2030-01-02")
        self.assertEqual(schedules[0]["start_time"], "10:00")
        self.assertEqual(schedules[0]["end_time"], "12:00")


    def test_password_reset_permissions_validation_and_private_audit(self):
        path='/students/20260001/reset-password'
        body={'new_password':'New-Password-2026!','reason':'本人忘记密码'}
        self.check(self.client.post(path,json=body),401)
        self.check(self.client.post(path,json=body,headers=self.headers()),403)
        self.check(self.client.post(path,json=body,headers=self.headers('admin1')),403)
        sup=self.headers('super')
        for invalid in [{**body,'new_password':'short'},{**body,'reason':'   '}]:
            self.assertGreaterEqual(self.client.post(path,json=invalid,headers=sup).status_code,400)
        self.check(self.client.post('/students/missing/reset-password',json=body,headers=sup),404)
        self.check(self.client.post(path,json=body,headers=sup))
        self.check(self.client.post('/auth/login',json={'kind':'student','account':'20260001','password':'TestPassword123!'}),401)
        self.check(self.client.post('/auth/login',json={'kind':'student','account':'20260001','password':body['new_password']}))
        logs=self.check(self.client.get('/operation-logs',headers=sup))
        reset=[r for r in logs if r['operation_type']=='RESET_PASSWORD']
        self.assertEqual(len(reset),1)
        self.assertEqual(reset[0]['reason'],body['reason'])
        self.assertNotIn(body['new_password'],json.dumps(logs))
        self.assertNotIn('password_hash',json.dumps(logs))

    def test_password_reset_linked_accounts_and_independent_admin(self):
        self.service.promote_student(self.seed['super'],'20260001','测试关联身份',[])
        with self.service.db.transaction() as c:
            c.execute('SELECT admin_id FROM admin WHERE student_id=%s',('20260001',))
            linked=c.fetchone()['admin_id']
        sup=self.headers('super')
        for path,password in [('/students/20260001/reset-password','Student-New-2026!'),
                              (f'/admins/{linked}/reset-password','Admin-New-2026!')]:
            self.check(self.client.post(path,json={'new_password':password,'reason':'核验关联账号'},headers=sup))
            for kind in ('student','admin'):
                self.check(self.client.post('/auth/login',json={'kind':kind,'account':'20260001','password':password}))
        self.check(self.client.post(f"/admins/{self.seed['normal']['id']}/reset-password",
            json={'new_password':'Independent-2026!','reason':'独立管理员重置'},headers=sup))
        self.check(self.client.post('/auth/login',json={'kind':'admin','account':'admin1','password':'Independent-2026!'}))
        self.check(self.client.post('/auth/login',json={'kind':'admin','account':'admin1','password':'TestPassword123!'}),401)
        self.check(self.client.post('/auth/login',json={'kind':'admin','account':'super','password':'TestPassword123!'}))

    def test_password_reset_audit_failure_rolls_back(self):
        with patch.object(self.service,'audit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.service.reset_password(self.seed['super'],'student','20260001','Not-Saved-2026!','审计异常')
        self.check(self.client.post('/auth/login',json={'kind':'student','account':'20260001','password':'TestPassword123!'}))
        self.check(self.client.post('/auth/login',json={'kind':'student','account':'20260001','password':'Not-Saved-2026!'}),401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
