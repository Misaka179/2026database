"""MySQL connections and serialized course-project write transactions."""
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .paths import DB_CONFIG, ROOT  # ROOT kept as a public alias

import pymysql
from pymysql.cursors import DictCursor


def config():
    path = Path(os.environ.get('VOLUNTEER_DB_CONFIG', DB_CONFIG)).expanduser()
    if not path.exists():
        raise RuntimeError(
            '数据库尚未配置：未找到配置文件 {path}。本机运行请先执行 '
            'python scripts/local_mysql.py start；使用外部数据库请设置 '
            'VOLUNTEER_DB_CONFIG 指向包含 host、port、user、password、database 的 JSON 文件。'
            .format(path=path))
    # utf-8-sig tolerates the BOM that Windows editors/Set-Content often add.
    return json.loads(path.read_text(encoding='utf-8-sig'))


class Database:
    def __init__(self, settings=None):
        self.settings = dict(settings or config())

    def connect(self):
        allowed = ('host', 'port', 'user', 'password', 'database')
        conn = pymysql.connect(**{k:v for k,v in self.settings.items() if k in allowed},
            charset='utf8mb4', cursorclass=DictCursor, autocommit=False,
            connect_timeout=5, read_timeout=15, write_timeout=15)
        with conn.cursor() as c:
            c.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            c.execute("SET time_zone = '+08:00'")
        return conn

    @contextmanager
    def transaction(self, write=False):
        conn = self.connect()
        lock = 'volunteer:' + self.settings['database']
        locked = False
        try:
            with conn.cursor() as c:
                if write:
                    # Small course deployment: serialize writes across API workers.
                    # The same lock covers capacity, credit and approval operations.
                    c.execute('SELECT GET_LOCK(%s, 10) AS acquired', (lock,))
                    if c.fetchone()['acquired'] != 1:
                        raise RuntimeError('数据库繁忙，请稍后重试')
                    locked = True
                conn.begin()
                yield c
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            if locked:
                try:
                    with conn.cursor() as c:
                        c.execute('SELECT RELEASE_LOCK(%s)', (lock,))
                finally:
                    conn.close()
            else:
                conn.close()


def one(c, sql, args=()):
    c.execute(sql, args)
    return c.fetchone()


def all_rows(c, sql, args=()):
    c.execute(sql, args)
    return c.fetchall()
