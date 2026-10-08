"""Chinese interface metadata and safe API feedback; no database is used."""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import sys
import unittest
from unittest.mock import patch

import os
os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE.parent / '.work' / 'python-packages'))

from fastapi.testclient import TestClient
from app.api import app, get_service, identity
from app.service import DomainError, Service


class StubService:
    def __init__(self, role='SUPER'):
        self.role = role
        self.db = self
        self.query = ''

    @contextmanager
    def transaction(self):
        yield self

    def actor(self, cursor, actor, roles):
        if self.role not in roles:
            raise DomainError('没有执行此操作的权限', 403)
        return {'_role': self.role}

    def execute(self, sql):
        self.query = sql

    def fetchall(self):
        return [{'admin_id': 1, 'name': '班次负责人', 'account': 'demo',
                 'role': 'NORMAL', 'status': 'ACTIVE'}]


class ScheduleReadDatabase:
    """Run the scoped read query against isolated in-memory SQL fixtures."""
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            CREATE TABLE student (student_id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE schedule (schedule_id INTEGER PRIMARY KEY, student_id TEXT,
                slot_id INTEGER, schedule_date TEXT);
            CREATE TABLE service_slot (slot_id INTEGER PRIMARY KEY, team_name TEXT,
                period_no INTEGER, start_time TEXT, end_time TEXT, location TEXT,
                manager_admin_id INTEGER);
            CREATE TABLE attendance (schedule_id INTEGER, attendance_status TEXT, source TEXT, revision INTEGER);
            CREATE TABLE leave_application (schedule_id INTEGER, approve_status TEXT);
            INSERT INTO student VALUES ('s1', '张三'), ('s2', '李四');
            INSERT INTO service_slot VALUES
                (1, '一分队', 1, '09:00', '11:00', '一楼', 1),
                (2, '二分队', 2, '14:00', '16:00', '二楼', 2);
            INSERT INTO schedule VALUES (1, 's1', 1, '2030-01-01'),
                (2, 's2', 2, '2030-01-01'), (3, 's2', 1, '2030-01-02');
        ''')

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, sql, args=()):
        self.cursor = self.connection.execute(sql.replace('%s', '?'), args)

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class ChineseInterfaceTests(unittest.TestCase):
    def setUp(self):
        original = dict(app.dependency_overrides)
        self.addCleanup(self.restore_overrides, original)
        self.service = StubService()
        app.dependency_overrides[get_service] = lambda: self.service
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    @staticmethod
    def restore_overrides(original):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)

    def assert_chinese(self, value):
        self.assertIsInstance(value, str)
        self.assertRegex(value, r'[\u4e00-\u9fff]')

    def test_workbench_and_documentation_are_local_chinese_pages(self):
        for path in ('/', '/docs'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('text/html', response.headers['content-type'])
                self.assertRegex(response.text, r'lang=["\']zh-CN["\']')
                self.assertNotIn('swagger-ui-bundle.js', response.text)
        response = self.client.get('/redoc', follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers['location'], '/docs')

    def test_all_operations_and_schema_titles_have_chinese_metadata(self):
        response = self.client.get('/openapi.json')
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertNotIn('/', schema['paths'])
        self.assertNotIn('/docs', schema['paths'])
        self.assertIn('get', schema['paths']['/admins'])
        for path, methods in schema['paths'].items():
            for method, operation in methods.items():
                with self.subTest(path=path, method=method):
                    self.assert_chinese(operation['summary'])
                    self.assert_chinese(operation['description'])
                    for parameter in operation.get('parameters', []):
                        self.assert_chinese(parameter['description'])
                        self.assert_chinese(parameter['schema']['title'])
                    for result in operation['responses'].values():
                        self.assert_chinese(result['description'])
        for model in schema['components']['schemas'].values():
            self.assert_chinese(model['title'])
            for field in model.get('properties', {}).values():
                self.assert_chinese(field['title'])
        validation = schema['components']['schemas']['HTTPValidationError']
        self.assertEqual(validation['properties']['detail']['type'], 'string')
        self.assertEqual(validation['properties']['errors']['type'], 'array')
        self.assertEqual(schema['components']['schemas']['Login']['properties']['kind']['enum'],
                         ['admin', 'student'])

    def test_validation_explains_errors_in_chinese_without_echoing_secrets(self):
        secret = 'never-echo-this-sensitive-value'
        response = self.client.post('/auth/login', json={
            'kind': 'invalid-role', 'account': '', 'password': [secret], secret: secret,
        })
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        self.assertNotIn('invalid-role', response.text)
        body = response.json()
        self.assert_chinese(body['detail'])
        self.assertTrue(body['errors'])
        for error in body['errors']:
            self.assertEqual(set(error), {'field', 'message'})
            self.assert_chinese(error['field'])
            self.assert_chinese(error['message'])

    def test_invalid_json_is_safe_and_chinese(self):
        response = self.client.post('/auth/login', content='{"password":"secret-content"',
                                    headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.assert_chinese(response.json()['detail'])
        self.assertNotIn('secret-content', response.text)

    def test_missing_login_unknown_resource_and_unsupported_method(self):
        for method, path, code in (('get', '/auth/me', 401), ('get', '/missing-page', 404),
                                    ('delete', '/auth/login', 405),
                                    ('get', '/static/missing-file.css', 404)):
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path)
                self.assertEqual(response.status_code, code)
                self.assert_chinese(response.json()['detail'])
                if code == 401:
                    self.assertEqual(response.headers['www-authenticate'], 'Bearer')

    def test_administrator_listing_requires_super_role_and_excludes_passwords(self):
        app.dependency_overrides[identity] = lambda: {'kind': 'admin', 'id': '1'}
        response = self.client.get('/admins')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()[0]), {'admin_id', 'name', 'account', 'role', 'status'})
        self.assertNotIn('password', self.service.query.lower())
        self.assertNotIn('*', self.service.query)
        for role in ('NORMAL', 'STUDENT'):
            with self.subTest(role=role):
                self.service.role = role
                response = self.client.get('/admins')
                self.assertEqual(response.status_code, 403)
                self.assert_chinese(response.json()['detail'])

    def test_unexpected_failure_does_not_expose_internal_details(self):
        def broken_service():
            raise OSError('private/database/internal-detail')
        app.dependency_overrides[get_service] = broken_service
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 500)
        self.assert_chinese(response.json()['detail'])
        self.assertNotIn('private', response.text)

    def test_schedule_names_keep_existing_role_scopes(self):
        database = ScheduleReadDatabase()
        self.addCleanup(database.connection.close)
        service = Service(db=database)
        cases = [('NORMAL', 1, [1, 3]), ('NORMAL', 2, [2]),
                 ('STUDENT', 's1', [1]), ('STUDENT', 's2', [2, 3]),
                 ('SUPER', 9, [1, 2, 3])]
        for role, actor_id, expected in cases:
            with self.subTest(role=role, actor_id=actor_id), patch.object(
                    service, 'actor', return_value={'_role': role, '_id': actor_id}):
                rows = service.list_schedules({})
                self.assertEqual([row['schedule_id'] for row in rows], expected)
                for row in rows:
                    self.assertEqual(row['student_name'], {'s1': '张三', 's2': '李四'}[row['student_id']])
                    self.assertNotIn('password_hash', row)

    def test_daily_action_documentation_matches_normal_admin_permissions(self):
        schema = self.client.get('/openapi.json').json()
        for path in ('/applications/leave/{leave_id}/decision', '/attendance'):
            self.assertIn('普通管理员', schema['paths'][path]['post']['description'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
