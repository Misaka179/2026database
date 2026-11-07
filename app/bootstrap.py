"""Explicit schema setup. Normal API credentials have no DDL privileges."""
import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path
from .db import Database, one
from .paths import ADMIN_CONFIG, CORE, DEMO_ACCOUNTS
from .security import hash_password

_test_hash = None


def statements(source):
    delimiter=';'
    buffer=[]
    for line in source.splitlines():
        if line.strip().startswith('--') or not line.strip():
            continue
        if line.strip().upper().startswith('DELIMITER '):
            if buffer:
                raise ValueError('Unexpected delimiter change in SQL')
            delimiter=line.strip().split(None,1)[1]
            continue
        buffer.append(line)
        if line.rstrip().endswith(delimiter):
            yield '\n'.join(buffer).rstrip()[:-len(delimiter)].strip()
            buffer=[]
    if buffer:
        raise ValueError('Unterminated SQL statement')


def initialize_database(settings, database='volunteer_core', demo=True, reset=False):
    global _test_hash
    if database not in ('volunteer_core','volunteer_core_test'):
        raise ValueError('Initializer only manages volunteer_core and volunteer_core_test')
    if reset and database != 'volunteer_core_test':
        raise ValueError('Reset is only permitted for the isolated test database')
    cfg=dict(settings)
    cfg.pop('database',None)
    # DDL only uses credentials explicitly supplied to the initializer.
    db=Database({**cfg,'database':'mysql'})
    with db.transaction() as c:
        c.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    db=Database({**cfg,'database':database})
    with db.transaction() as c:
        c.execute('SHOW TABLES')
        tables=c.fetchall()
        if reset and tables:
            # Strictly confined to the separately named disposable test database.
            c.execute('SET FOREIGN_KEY_CHECKS=0')
            try:
                for item in tables:
                    table=next(iter(item.values()))
                    if not re.fullmatch('[a-z_]+',table):
                        raise ValueError('Unexpected test table name')
                    c.execute(f'DROP TABLE `{table}`')
            finally:
                c.execute('SET FOREIGN_KEY_CHECKS=1')
            tables=[]
        if not tables:
            for filename in ('schema.sql','constraints.sql'):
                # utf-8-sig tolerates a BOM if the SQL file was re-saved on Windows.
                # CORE stays a module-level name so callers/tests can redirect the SQL dir.
                for stmt in statements((CORE/'sql'/filename).read_text(encoding='utf-8-sig')):
                    c.execute(stmt)
        elif not {'student','admin','service_slot','schedule','attendance','service_record','credit_log','operation_log'}.issubset({next(iter(t.values())) for t in tables}):
            raise RuntimeError('Existing schema is incomplete; refusing to overwrite it')
        trigger_count=one(c,'SELECT COUNT(*) AS n FROM information_schema.triggers WHERE trigger_schema=%s',(database,))['n']
        if trigger_count != 12:
            raise RuntimeError('Database constraints are incomplete; refusing to initialize business data')
        if not demo:
            return {}
        if one(c,'SELECT admin_id FROM admin LIMIT 1'):
            return {'already_initialized':True}
        password='TestPassword123!' if database.endswith('_test') else 'Demo-'+secrets.token_urlsafe(12)
        if database=='volunteer_core':
            # Persist access details before committing accounts, so a filesystem
            # failure cannot leave initialized demo accounts with unknown passwords.
            DEMO_ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
            DEMO_ACCOUNTS.write_text(json.dumps({'note':'仅用于本机课程演示；真实部署前更换密码',
                'password':password,'accounts':{'admin':['super','admin1','admin2'],'student':['20260001','20260002']}},ensure_ascii=False,indent=2),encoding='utf-8')
        if database.endswith('_test'):
            if _test_hash is None:
                _test_hash=hash_password(password)
            hashed=_test_hash
        else:
            hashed=hash_password(password)
        admins=[]
        for name,account,role in [('超级管理员','super','SUPER'),('一分队管理员','admin1','NORMAL'),('二分队管理员','admin2','NORMAL')]:
            c.execute('INSERT INTO admin(name,account,password_hash,role) VALUES(%s,%s,%s,%s)',(name,account,hashed,role))
            admins.append(c.lastrowid)
        for sid,name in [('20260001','张三'),('20260002','李四')]:
            c.execute('INSERT INTO student(student_id,name,college,phone,password_hash) VALUES(%s,%s,%s,%s,%s)',(sid,name,'示例学院','',hashed))
        slots=[]
        for team,start,end,manager in [('一分队','10:00','12:00',admins[1]),('二分队','14:00','16:00',admins[2])]:
            c.execute('''INSERT INTO service_slot(team_name,period_no,start_time,end_time,location,
                need_num,service_minutes,manager_admin_id) VALUES(%s,1,%s,%s,'图书馆',2,120,%s)''',(team,start,end,manager))
            slots.append(c.lastrowid)
        for kind,score in [('LATE',2),('ABSENT',3)]:
            c.execute('INSERT INTO credit_rule(violation_type,version,deduct_score,create_admin_id) VALUES(%s,1,%s,%s)',(kind,score,admins[0]))
    demo_data={'super':{'kind':'admin','id':admins[0]},'normal':{'kind':'admin','id':admins[1]},
        'other_admin':{'kind':'admin','id':admins[2]},'student':{'kind':'student','id':'20260001'},
        'other_student':{'kind':'student','id':'20260002'},'slot':slots[0],'other_slot':slots[1]}
    return demo_data


def admin_config_path(explicit):
    """Resolve the JSON config that supplies DDL-capable credentials.

    Precedence: --config, VOLUNTEER_ADMIN_CONFIG, VOLUNTEER_DB_CONFIG, then the
    private instance's admin.json. The last two let an external MySQL deployment
    work without a local ``.work/mysql-core`` directory.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    for variable in ('VOLUNTEER_ADMIN_CONFIG', 'VOLUNTEER_DB_CONFIG'):
        value = os.environ.get(variable, '').strip()
        if value:
            return Path(value).expanduser()
    return ADMIN_CONFIG


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Initialize the dedicated volunteer database')
    parser.add_argument('--config',type=Path,default=None,
        help='含初始化账号（需要建库/建表/建触发器权限）的 JSON；默认取 '
             'VOLUNTEER_ADMIN_CONFIG、VOLUNTEER_DB_CONFIG 或 .work/mysql-core/admin.json')
    args=parser.parse_args()
    config_path=admin_config_path(args.config)
    if not config_path.is_file():
        print(f'初始化失败：未找到数据库配置 {config_path}。本机运行请先执行 '
              'python scripts/local_mysql.py start；使用外部数据库请设置 '
              'VOLUNTEER_ADMIN_CONFIG 或 VOLUNTEER_DB_CONFIG 指向含 host、port、user、'
              'password、database 的 JSON 配置（该账号需要建库、建表和创建触发器权限）。',
              file=sys.stderr)
        raise SystemExit(1)
    # utf-8-sig tolerates the BOM that Windows editors/Set-Content often add.
    settings=json.loads(config_path.read_text(encoding='utf-8-sig'))
    result=initialize_database(settings)
    from .fixed_slots import migrate
    migrate({**settings,'database':'volunteer_core'})
    print('数据库已升级，保留现有数据。' if result.get('already_initialized') else
          f'多业务数据表、84 个固定时段、花园 A/B 岗及演示账户已初始化。账户信息保存在 {DEMO_ACCOUNTS}。')
