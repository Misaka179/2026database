"""Explicit local demo provisioning; never invoked during application startup."""
import json
import secrets
import sys
from datetime import datetime
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
from app.db import all_rows, one
from app.security import hash_password, verify_password
from app.service import Service, require


def main():
    root = CORE.parent
    output = root / 'outputs/test-admins'
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'business-accounts.json'
    service = Service()
    demo = json.loads((root / '.work/demo-accounts.json').read_text(encoding='utf-8'))
    actor = service.login('admin', 'super', demo['password'])
    with service.db.transaction() as c:
        service.actor(c, actor, ('SUPER',))
        slots = all_rows(c, """SELECT t.*,b.code,b.name AS business_name FROM service_slot t
            JOIN business b ON b.business_id=t.business_id WHERE b.code IN ('ART','GARDEN','PUBLICITY')
            AND t.status='ACTIVE' ORDER BY b.business_id,t.weekday,t.period_no""")
        businesses = all_rows(c, "SELECT * FROM business WHERE code IN ('GARDEN','PUBLICITY') ORDER BY business_id")
    art = [s for s in slots if s['code']=='ART']
    require(len(art)==28 and len(businesses)==2, '新增业务时段尚未完整初始化')
    targets = [{'account':f"test_art_w{s['weekday']}_p{s['period_no']}",
                'name':f"美育测试管理员 · 周{s['weekday']}第{s['period_no']}时段",
                'slot_ids':[s['slot_id']], 'business_id':s['business_id'], 'scope':'SLOT'} for s in art]
    targets += [{'account':f"test_{b['code'].lower()}", 'name':b['name']+'测试管理员',
                 'slot_ids':[s['slot_id'] for s in slots if s['business_id']==b['business_id']],
                 'business_id':b['business_id'], 'scope':'BUSINESS'} for b in businesses]
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        require(manifest['database']==service.db.settings['database'], '账号清单数据库不匹配')
        require([{k:a[k] for k in t} for a,t in zip(manifest['accounts'],targets)]==targets
                and len(manifest['accounts'])==len(targets), '保存的测试账号管理范围与当前目录不一致')
    else:
        manifest = {'database':service.db.settings['database'], 'accounts':[
            {**t,'password':'Test-'+secrets.token_urlsafe(12)} for t in targets]}
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    prepared = [(a,hash_password(a['password'])) for a in manifest['accounts']]
    created = assigned = 0
    with service.db.transaction(True) as c:
        owner = service.actor(c,actor,('SUPER',))
        for item,encoded in prepared:
            old = one(c,'SELECT * FROM admin WHERE account=%s',(item['account'],))
            if old:
                require(old['role']=='NORMAL' and old['status']=='ACTIVE' and not old['student_id']
                        and old['name']==item['name'] and verify_password(item['password'],old['password_hash']),
                        '测试账号已被修改，未覆盖账号：'+item['account'])
                admin_id = old['admin_id']
            else:
                c.execute("INSERT INTO admin(name,account,password_hash,role) VALUES(%s,%s,%s,'NORMAL')",
                          (item['name'],item['account'],encoded))
                admin_id = c.lastrowid
                service.audit(c,owner['_id'],'CREATE_ADMIN','admin',admin_id,
                              after={'account':item['account'],'role':'NORMAL'},reason='按要求配置多业务测试管理员')
                created += 1
            if item['scope']=='BUSINESS':
                before = one(c,'SELECT * FROM business WHERE business_id=%s',(item['business_id'],))
                require(before['manager_admin_id'] in (None,admin_id),'业务已配置其他负责人，未覆盖')
                if before['manager_admin_id'] != admin_id:
                    c.execute('UPDATE business SET manager_admin_id=%s WHERE business_id=%s',(admin_id,item['business_id']))
                    service.audit(c,owner['_id'],'CONFIGURE_BUSINESS','business',item['business_id'],
                                  {'manager_admin_id':None},{'manager_admin_id':admin_id},'配置测试业务管理员')
            for slot_id in item['slot_ids']:
                before = one(c,'SELECT * FROM service_slot WHERE slot_id=%s FOR UPDATE',(slot_id,))
                require(before['manager_admin_id'] in (None,admin_id),'时段已有其他负责人，未覆盖')
                if before['manager_admin_id'] != admin_id:
                    c.execute('UPDATE service_slot SET manager_admin_id=%s WHERE slot_id=%s',(admin_id,slot_id))
                    service.audit(c,owner['_id'],'CONFIGURE_SLOT','service_slot',slot_id,
                                  {'manager_admin_id':None,'need_num':before['need_num']},
                                  {'manager_admin_id':admin_id,'need_num':before['need_num']},'配置测试负责人，保留原容量')
                    assigned += 1
        service.sync_semesters(c)
    known = {a:demo['password'] for a in demo['accounts']['admin']}
    consult = json.loads((output/'accounts.json').read_text(encoding='utf-8'))
    require(consult['database']==service.db.settings['database'],'咨询账号清单数据库不匹配')
    known.update({a['account']:a['password'] for a in consult['accounts']})
    known.update({a['account']:a['password'] for a in manifest['accounts']})
    with service.db.transaction() as c:
        admins = all_rows(c,'SELECT admin_id,account,name,role,status FROM admin ORDER BY admin_id')
        scopes = all_rows(c,"""SELECT t.*,b.name AS business_name,b.code FROM service_slot t
            JOIN business b ON b.business_id=t.business_id ORDER BY b.business_id,t.weekday,t.period_no""")
        extra = all_rows(c,"SELECT name FROM business WHERE manager_scope='NONE' ORDER BY business_id")
    verified=[]
    for a in admins:
        password=known.get(a['account'])
        if password:
            identity=service.login('admin',a['account'],password)
            require(identity['id']==a['admin_id'],'登录身份不匹配')
        managed=[s for s in scopes if s['manager_admin_id']==a['admin_id']]
        if a['account'].startswith(('test_art_','test_garden','test_publicity')):
            target=next(t for t in targets if t['account']==a['account'])
            require({s['slot_id'] for s in managed}==set(target['slot_ids']),'管理范围核验失败')
        scope = '所有业务、账号管理与审核' if a['role']=='SUPER' else '；'.join(
            f"{s['business_name']} {('周'+str(s['weekday'])+' 第'+str(s['period_no'])+'时段') if s['weekday'] else s['team_name']}"
            + ('（已停用）' if s['status']!='ACTIVE' else '') for s in managed) or '未分配管理范围'
        verified.append({**a,'password':password,'scope':scope})
    lines=['# 各业务管理员测试账号清单','',f'更新时间：{datetime.now():%Y-%m-%d %H:%M}',
           '', '登录地址：http://127.0.0.1:8765/。所有以下账号登录时均选择“管理员”，super登录后自动拥有超级管理员权限。',
           '', '各账号密码均已逐一验证；原有密码未修改。清单仅存放在本机，包含可直接登录的密码。',
           '', '美育每个时段一位管理员；开心花园一位管理员统一管理A/B岗；青广宣传一位管理员统一管理全部21个时段。',
           '', '咨询服务保留原35个测试管理员。admin1、admin2是旧演示管理员，其现有范围在下表标注。',
           '', '以下非固定业务由超级管理员管理征集、审批和专项导入，无独立普通管理员：'+ '、'.join(b['name'] for b in extra)+'。',
           '', '新增业务配置了负责人，但仍需设置容量及实际队员归属后才能查看相应出勤记录。',
           '', '| 账号 | 密码 | 名称 | 实际管理范围 |','|---|---|---|---|']
    for a in sorted(verified,key=lambda a:(a['role']!='SUPER',a['admin_id'])):
        lines.append(f"| `{a['account']}` | `{a['password'] or '未保存明文密码'}` | {a['name']} | {a['scope']} |")
    (output/'全部业务管理员账号.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'全部业务管理员账号.json').write_text(json.dumps({'login':'http://127.0.0.1:8765/','accounts':verified},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'created':created,'assigned_slots':assigned,'verified_login_accounts':sum(bool(a['password']) for a in verified),
                      'total_admins':len(verified),'report':str(output/'全部业务管理员账号.md')},ensure_ascii=False))


if __name__=='__main__':
    main()
