"""Explicit schema setup. Normal API credentials have no DDL privileges."""
import argparse
import json
import re
import secrets
from pathlib import Path
from .db import Database, ROOT, one
from .security import hash_password

CORE = Path(__file__).resolve().parents[1]
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
                for stmt in statements((CORE/'sql'/filename).read_text(encoding='utf-8')):
                    c.execute(stmt)
        elif len(tables) not in (13,14,15,16,17):
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
            (ROOT/'.work/demo-accounts.json').write_text(json.dumps({'note':'仅用于本机课程演示；真实部署前更换密码',
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


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Initialize the dedicated volunteer database')
    parser.add_argument('--config',type=Path,default=ROOT/'.work/mysql-core/admin.json')
    args=parser.parse_args()
    result=initialize_database(json.loads(args.config.read_text(encoding='utf-8')))
    from .fixed_slots import migrate
    migrate({**json.loads(args.config.read_text(encoding='utf-8')),'database':'volunteer_core'})
    print('数据库已升级，保留现有数据。' if result.get('already_initialized') else '17 张表、35 个固定时段及演示账户已初始化。账户信息保存在 .work/demo-accounts.json。')
