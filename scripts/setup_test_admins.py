"""Explicit local test-admin provisioning; never runs during normal startup."""
import argparse
import json
from pathlib import Path
import secrets
import sys

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
from app.db import all_rows, one
from app.security import hash_password, verify_password
from app.service import Service, require


def provision(service, actor, accounts):
    prepared = [(item, hash_password(item['password'])) for item in accounts]
    with service.db.transaction(True) as c:
        admin = service.actor(c, actor, ('SUPER',))
        slots = all_rows(c, "SELECT * FROM service_slot WHERE weekday IS NOT NULL AND status='ACTIVE' ORDER BY weekday,period_no")
        require(len(slots)==35, '必须先完成 35 个固定时段初始化')
        expected = {s['slot_id']:s for s in slots}
        require(len(accounts)==35 and {a['slot_id'] for a in accounts}==set(expected), '测试账号清单与固定时段不匹配')
        result = {'created':0,'assigned':0,'preserved':0}
        for item, encoded in prepared:
            slot = expected[item['slot_id']]
            require(item['account']==f"test_w{slot['weekday']}_p{slot['period_no']}", '测试账号命名不匹配')
            name = '测试管理员 · '+slot['team_name']
            existing = one(c, 'SELECT * FROM admin WHERE account=%s', (item['account'],))
            if existing:
                require(existing['role']=='NORMAL' and existing['status']=='ACTIVE' and
                        not existing.get('student_id') and existing['name']==name and
                        verify_password(item['password'],existing['password_hash']),
                        '同名账号与保存的测试清单不一致，未覆盖账号')
                manager = existing['admin_id']
            else:
                c.execute("INSERT INTO admin(name,account,password_hash,role) VALUES(%s,%s,%s,'NORMAL')",
                          (name,item['account'],encoded))
                manager = c.lastrowid
                service.audit(c,admin['_id'],'CREATE_ADMIN','admin',manager,
                              after={'account':item['account'],'role':'NORMAL','test_slot':slot['slot_id']},reason='为固定时段配置测试管理员')
                result['created'] += 1
            if slot['manager_admin_id'] is None:
                c.execute('UPDATE service_slot SET manager_admin_id=%s WHERE slot_id=%s',(manager,slot['slot_id']))
                service.audit(c,admin['_id'],'CONFIGURE_SLOT','service_slot',slot['slot_id'],
                              {'manager_admin_id':None,'need_num':slot['need_num']},
                              {'manager_admin_id':manager,'need_num':slot['need_num']},'配置测试管理员，保留原人数上限')
                result['assigned'] += 1
            elif slot['manager_admin_id'] != manager:
                result['preserved'] += 1
        service.sync_semesters(c)
        return result


def main():
    parser=argparse.ArgumentParser(description='为每个固定时段建立独立测试管理员，保留已有非测试负责人')
    parser.add_argument('--super-account',required=True)
    parser.add_argument('--output',type=Path,default=CORE.parent/'outputs/test-admins/accounts.json')
    args=parser.parse_args()
    service=Service()
    with service.db.transaction() as c:
        admin=one(c,"SELECT admin_id FROM admin WHERE account=%s AND role='SUPER' AND status='ACTIVE'",(args.super_account,))
        require(admin,'请指定有效超级管理员账号')
        slots=all_rows(c,"SELECT slot_id,team_name,weekday,period_no FROM service_slot WHERE weekday IS NOT NULL AND status='ACTIVE' ORDER BY weekday,period_no")
    if args.output.exists():
        manifest=json.loads(args.output.read_text(encoding='utf-8'))
        require(manifest['database']==service.db.settings['database'],'清单数据库不匹配')
    else:
        manifest={'database':service.db.settings['database'],'login':'http://127.0.0.1:8765/',
                  'kind':'admin','accounts':[{**s,'account':f"test_w{s['weekday']}_p{s['period_no']}",
                  'password':'Test-'+secrets.token_urlsafe(12)} for s in slots]}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        # Save recoverable credentials before committing any accounts.
        args.output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    result=provision(service,{'kind':'admin','id':admin['admin_id']},manifest['accounts'])
    lines=['# 固定时段测试管理员','', '登录工作台时选择“管理员”。各账号只负责对应时段，密码各不相同。',
           '清单包含测试密码，请仅在本地项目中使用。原人数上限、队员归属、服务时长与信用分保持不变。','',
           '| 时段 | 管理员账号 | 测试密码 |','|---|---|---|']
    lines.extend(f"| {a['team_name']} | `{a['account']}` | `{a['password']}` |" for a in manifest['accounts'])
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    print(f'账号清单：{args.output.with_suffix(".md")}')


if __name__=='__main__':
    main()
