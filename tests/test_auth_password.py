"""HTTP tests for self-service password change and reset requests.

Run with the other tests using unittest's serial discovery. This module resets
the disposable volunteer_core_test database, so do not run it concurrently with
another test process. No main-database data is modified.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'

CORE = Path(__file__).resolve().parents[1]
WORKSPACE = CORE.parent
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(WORKSPACE / ".work" / "python-packages"))

from fastapi.testclient import TestClient
from app.api import app, get_service
from app.bootstrap import initialize_database
from app.db import Database, all_rows
from app.fixed_slots import migrate
from app.paths import WEB_ROOT
from app.service import Service

OLD_PASSWORD = 'TestPassword123!'
CHANGE = '/auth/password/change'
RESET_REQUEST = '/auth/password/reset-request'


class AuthPasswordTests(unittest.TestCase):
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
        # Install the additive tables (inbox_notice and friends) as the API server would.
        migrate({**self.admin_settings, "database": "volunteer_core_test"})
        self.service = Service(
            Database(self.runtime_settings), clock=lambda: datetime(2030, 1, 1, 0, 0)
        )
        environment = patch.dict(
            os.environ,
            {"VOLUNTEER_TOKEN_SECRET": "auth-password-test-only-fixed-key-not-for-production"},
        )
        environment.start()
        self.addCleanup(environment.stop)
        original_overrides = dict(app.dependency_overrides)
        self.addCleanup(self.restore_overrides, original_overrides)
        app.dependency_overrides[get_service] = lambda: self.service
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    @staticmethod
    def restore_overrides(original):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)

    def check(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def login(self, kind, account, password=OLD_PASSWORD):
        return self.client.post("/auth/login", json={"kind": kind, "account": account,
                                                     "password": password})

    def headers(self, kind, account, password=OLD_PASSWORD):
        result = self.check(self.login(kind, account, password))
        return {"Authorization": "Bearer " + result["access_token"]}

    def rows(self, sql, args=()):
        with self.service.db.transaction() as c:
            return list(all_rows(c, sql, args))

    def test_change_password_rejects_same_as_current(self):
        headers = self.headers("student", "20260001")
        response = self.client.post(
            CHANGE,
            json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
            headers=headers,
        )
        body = self.check(response, 400)
        self.assertIn("密码与原密码一致", body["detail"])
        self.check(self.login("student", "20260001"), 200)

    def test_change_password_requires_login_and_validates(self):
        valid = {"current_password": OLD_PASSWORD, "new_password": "New-Student-2026!"}
        self.check(self.client.post(CHANGE, json=valid), 401)
        headers = self.headers("student", "20260001")
        wrong = self.check(self.client.post(CHANGE, headers=headers, json={
            "current_password": "Wrong-Password!", "new_password": "New-Student-2026!"}), 401)
        self.assertEqual(wrong["detail"], "当前密码不正确")
        for invalid in ({**valid, "new_password": "short"},
                        {**valid, "new_password": "x" * 129},
                        {**valid, "current_password": ""},
                        {**valid, "role": "SUPER"}):
            with self.subTest(body=invalid):
                self.check(self.client.post(CHANGE, headers=headers, json=invalid), 422)
        # Failed attempts must not change the stored hash.
        self.check(self.login("student", "20260001"), 200)
        self.assertEqual(self.rows("SELECT * FROM operation_log WHERE operation_type='CHANGE_PASSWORD'"), [])

    def test_student_change_password_updates_login_and_notifies_super_only(self):
        headers = self.headers("student", "20260001")
        new_password = "New-Student-2026!"
        result = self.check(self.client.post(CHANGE, headers=headers, json={
            "current_password": OLD_PASSWORD, "new_password": new_password}))
        self.assertEqual(result, {"status": "UPDATED"})
        self.assertEqual(self.login("student", "20260001").status_code, 401)
        self.check(self.login("student", "20260001", new_password), 200)
        # A student cannot be the operation_log.admin_id foreign key: no audit row.
        self.assertEqual(self.rows("SELECT * FROM operation_log WHERE operation_type='CHANGE_PASSWORD'"), [])
        notices = self.service.inbox(self.seed["super"])["items"]
        changed = [n for n in notices if n["title"] == "账号密码已修改"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["target_page"], "basics")
        self.assertIn("20260001", changed[0]["message"])
        self.assertIn("2030-01-01", changed[0]["message"])
        # Only SUPER accounts are notified.
        self.assertFalse([n for n in self.service.inbox(self.seed["normal"])["items"]
                          if n["title"] == "账号密码已修改"])

    def test_admin_change_password_is_independent_from_volunteer(self):
        self.service.create_admin(self.seed["super"], "独立管理员", "independent-admin", OLD_PASSWORD)
        independent_headers = self.headers("admin", "independent-admin")
        self.check(self.client.post(CHANGE, headers=independent_headers, json={
            "current_password": OLD_PASSWORD, "new_password": "Independent-2026!"}))
        self.check(self.login("admin", "independent-admin", "Independent-2026!"), 200)
        self.assertEqual(self.login("admin", "independent-admin").status_code, 401)
        self.check(self.login("student", "20260001"), 200)
        logs = self.rows("SELECT * FROM operation_log WHERE operation_type='CHANGE_PASSWORD'")
        self.assertEqual(len(logs), 1)
        self.assertTrue(all(row["reason"] == "本人在线修改密码" for row in logs))
        self.assertNotIn("pbkdf2", json.dumps(logs, default=str))

    def test_admin_creation_has_no_volunteer_link_or_copied_password(self):
        self.service.create_admin(self.seed["super"], "独立管理员", "independent-admin", "AdminOwnPass123!")
        row = self.rows("SELECT student_id FROM admin WHERE account=%s",("independent-admin",))[0]
        self.assertIsNone(row["student_id"])
        self.assertEqual(self.login("admin", "independent-admin", OLD_PASSWORD).status_code, 401)
        self.check(self.login("admin", "independent-admin", "AdminOwnPass123!"), 200)

    def test_disabled_admin_cannot_change_password_with_old_token(self):
        headers = self.headers("admin", "admin1")
        with self.service.db.transaction(True) as c:
            c.execute("UPDATE admin SET status='DISABLED' WHERE account=%s", ("admin1",))
        denied = self.check(self.client.post(CHANGE, headers=headers, json={
            "current_password": OLD_PASSWORD, "new_password": "Disabled-Admin-2026!"}), 403)
        self.assertIn("停用", denied["detail"])

    def test_reset_request_requires_exact_identity_and_notifies_super(self):
        valid = {"kind": "student", "account": " 20260001 ", "name": " 张三 ",
                 "phone": "13800000000", "reason": "忘记密码"}
        accepted = {"status": "ACCEPTED"}
        mismatch_cases = [
            ({**valid, "name": "王五"}, "学号或姓名不正确，请检查后重试。"),
            ({**valid, "name": "张"}, "学号或姓名不正确，请检查后重试。"),
            ({**valid, "account": "20990000"}, "学号或姓名不正确，请检查后重试。"),
            ({**valid, "kind": "admin", "account": "20260001"},
             "管理员账号或姓名不正确，请检查后重试。"),
        ]
        for body, detail in mismatch_cases:
            with self.subTest(body=body):
                response = self.client.post(RESET_REQUEST, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"], detail)
        self.assertEqual([row for row in self.rows("SELECT * FROM inbox_notice")
                          if row["event_key"].startswith("password-reset:")], [])

        self.assertEqual(self.check(self.client.post(RESET_REQUEST, json=valid)), accepted)
        notices = [row for row in self.rows("SELECT * FROM inbox_notice")
                   if row["event_key"].startswith("password-reset:")]
        self.assertEqual(len(notices), 1)
        notice = notices[0]
        self.assertEqual(notice["event_key"], "password-reset:student:20260001:2030-01-01")
        self.assertEqual(notice["recipient_kind"], "admin")
        self.assertEqual(str(notice["recipient_id"]), str(self.seed["super"]["id"]))
        self.assertEqual(notice["category"], "ACCOUNT")
        self.assertEqual(notice["title"], "密码重置申请")
        self.assertEqual(notice["target_page"], "basics")
        self.assertEqual(notice["target_id"], "20260001")
        for text in ("student", "20260001", "张三", "13800000000", "忘记密码"):
            self.assertIn(text, notice["message"])
        # Repeating the same request on the same day is deduplicated, never duplicated.
        self.check(self.client.post(RESET_REQUEST, json=valid))
        self.assertEqual(len([row for row in self.rows("SELECT * FROM inbox_notice")
                              if row["event_key"].startswith("password-reset:")]), 1)
        # An administrator account can request a reset too, but its account and
        # name must also be an exact same-record match.
        admin_valid = {"kind": "admin", "account": "super", "name": "超级管理员"}
        self.check(self.client.post(RESET_REQUEST, json=admin_valid))
        bad_admin = self.client.post(RESET_REQUEST, json={**admin_valid, "name": "管理员"})
        self.assertEqual(bad_admin.status_code, 422)
        self.assertEqual(bad_admin.json()["detail"], "管理员账号或姓名不正确，请检查后重试。")
        keys = [row["event_key"] for row in self.rows("SELECT * FROM inbox_notice")
                if row["event_key"].startswith("password-reset:")]
        self.assertEqual(sorted(keys), ["password-reset:admin:super:2030-01-01",
                                        "password-reset:student:20260001:2030-01-01"])
        # A public request must not write the audit table.
        self.assertEqual(self.rows("SELECT * FROM operation_log"), [])

    def test_reset_request_rejects_invalid_lengths_and_kinds(self):
        valid = {"kind": "student", "account": "20260001", "name": "张三"}
        for invalid in ({**valid, "kind": "teacher"},
                        {"kind": "student", "account": "20260001"},
                        {**valid, "account": "x" * 65},
                        {**valid, "name": "名" * 65},
                        {**valid, "phone": "1" * 21},
                        {**valid, "reason": "说" * 501},
                        {**valid, "role": "SUPER"}):
            with self.subTest(body=invalid):
                self.check(self.client.post(RESET_REQUEST, json=invalid), 422)
        self.assertEqual(self.rows("SELECT * FROM inbox_notice"), [])

    @unittest.skipUnless((WEB_ROOT / "password.html").exists(),
                         "web/password.html 由前端提供，尚未创建")
    def test_password_page_serves_html_without_cache(self):
        response = self.client.get("/password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertEqual(response.headers.get("cache-control"), "no-cache")
        schema = self.client.get("/openapi.json").json()
        self.assertNotIn("/password", schema["paths"])
        for path in (CHANGE, RESET_REQUEST):
            self.assertIn(path, schema["paths"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
