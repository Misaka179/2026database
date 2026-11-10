"""Identity-safe business/group roster import; never recognizes service hours."""
import hashlib
import json
from datetime import timedelta

from .db import all_rows, one
from .import_common import (MAX_BYTES, OK, PENDING, SKIP, decode, evaluate, merge_people,
                            read_sheets, sid_problem)
from .security import hash_password

SHEET_GROUPS = {'综运': '综合运营中心', '图志之家': '图志之家', '活策': '活动策划中心',
                '物资采购': '物资采购中心', '宣传': '宣传推广中心', '音视频': '音视频制作中心',
                '摄影摄像': '摄影摄像中心', '青广': '青广干事'}


def parse_roster(encoded):
    """Return (raw bytes, sheets, rows) using the shared header rule."""
    from .service import DomainError
    try:
        raw = decode(encoded)
        sheets, rows = read_sheets(raw)
    except ValueError as exc:
        raise DomainError(str(exc), 422) from exc
    except Exception as exc:
        raise DomainError('请上传有效且含姓名、学号表头的 .xlsx 文件', 422) from exc
    for sheet in sheets:
        sheet['group_name'] = SHEET_GROUPS.get(sheet['name'])
        sheet['business_name'] = ('明远学术汇' if sheet['name'] == '明远学术'
                                  else '干部及干事' if sheet['name'] in SHEET_GROUPS else None)
    return raw, sheets, rows


class MemberImport:
    def _default_target(self, catalogue, groups, sheet):
        b = next((b for b in catalogue if b['name'] == sheet.get('business_name')), None)
        if not b:
            return None
        g = next((g for g in groups if g['business_id'] == b['business_id']
                  and g['name'] == sheet.get('group_name')), None)
        return {'business_id': b['business_id'], 'group_id': g['group_id'] if g else None}

    def import_members(self, actor, file_base64, mappings=None, decisions=None, commit=False,
                       initial_password=None, scope=None, approvals=None):
        """Preview or commit a non-fixed business/group roster.

        ``approvals`` marks the rows the operator explicitly accepted; anything
        pending that is not approved is simply left out (never an error).
        """
        from .service import require, require_business_owner
        with self.db.transaction() as c:
            self.actor(c, actor, ('SUPER', 'NORMAL'))
        raw, sheets, rows = parse_roster(file_base64)
        scope = scope_ref(scope)
        mappings = mappings or {}
        decisions = decisions or {}
        approvals = {str(k): bool(v) for k, v in (approvals or {}).items()}
        skip_rows = {k for k, v in decisions.items() if isinstance(v, dict) and v.get('skip')}
        for key, value in decisions.items():
            if isinstance(value, dict) and value.get('confirmed'):
                row = next((r for r in rows if r['key'] == key), None)
                if row and row['student_id']:
                    approvals[row['student_id']] = True
        all_people = merge_people(rows)
        prehashed = {}
        if commit:
            # 与固定业务导入一致：先只读校验账号角色并确认要建号的人，锁外完成慢哈希
            with self.db.transaction() as c0:
                self.actor(c0, actor, ('SUPER', 'NORMAL'))
                missing = [p['student_id'] for p in all_people
                           if not one(c0, 'SELECT 1 FROM student WHERE student_id=%s', (p['student_id'],))]
            if missing:
                require(initial_password and 8 <= len(initial_password) <= 128,
                        '请填写 8 至 128 字符的新账号初始密码', 422)
                prehashed = {sid: hash_password(initial_password) for sid in missing}
        with self.db.transaction(True if commit else False) as c:
            a = self.actor(c, actor, ('SUPER', 'NORMAL'))
            catalogue = all_rows(c, 'SELECT * FROM business')
            group_rows = all_rows(c, 'SELECT * FROM business_group')
            resolved = {}
            for sheet in sheets:
                target = mappings.get(sheet['name']) or self._default_target(catalogue, group_rows, sheet)
                if target:
                    b = self._active_business(c, int(target['business_id']))
                    require(b['kind'] != 'FIXED', '该入口只导入非固定业务／小组名单，固定业务请配置时段归属', 422)
                    require_business_owner(c, a, b['business_id'], '只能管理本人负责业务的名单')
                    groups = [g for g in group_rows if g['business_id'] == b['business_id']]
                    if target.get('group_id'):
                        self._group(c, b['business_id'], int(target['group_id']))
                    elif groups:
                        require(False, f'“{b["name"]}”已划分小组，请先选择小组；未分组的名单请先在业务中建立小组', 422)
                    target = {'business_id': b['business_id'],
                              'group_id': int(target['group_id']) if target.get('group_id') else None}
                    sheet['business_name'] = b['name']
                    sheet['group_name'] = next((g['name'] for g in groups
                                                if g['group_id'] == target['group_id']), None)
                resolved[sheet['name']] = target
                sheet['target'] = target
            people = all_people
            existing = {p['student_id']: p for p in all_rows(c, 'SELECT * FROM student')}
            errors, pending, credits, verdicts, formula_keys = [], [], [], {}, set()
            for row in rows:
                if row['key'] in skip_rows or resolved.get(row['sheet']) is None:
                    continue
                problem = sid_problem(row['student_id'])
                if not problem and not row['name']:
                    problem = '缺少姓名'
                if not problem and (len(row['name']) > 100 or len(row['college']) > 100):
                    problem = f'第 {row["row"]} 行姓名或学院超过 100 字'
                if problem:
                    errors.append({'key': row['key'], 'message': f'第 {row["row"]} 行：{problem}'})
                elif row['formula']:
                    formula_keys.add(row['key'])
            for person in people:
                sid = person['student_id']
                targets = []
                for row in person_rows(rows, sid):
                    if row['key'] in skip_rows or resolved.get(row['sheet']) is None:
                        continue
                    target = resolved[row['sheet']]
                    stamp = (target['business_id'], target['group_id'])
                    if stamp not in targets:
                        targets.append(stamp)
                if not targets:
                    continue
                verdict = evaluate(person, existing.get(sid), approvals.get(sid))
                if verdict['status'] == OK and formula_keys.intersection(person['keys']) and not approvals.get(sid):
                    verdict = {'status': PENDING, 'issue': 'formula', 'detail': '姓名或学号是公式且无缓存值，请确认该行',
                               'approved': False, 'new': verdict['new']}
                verdicts[sid] = verdict
                verdict['targets'] = targets
                person['targets'] = targets
                person['status'] = verdict['status']
                person['issue'] = verdict['issue']
                person['detail'] = verdict['detail']
                person['new'] = verdict['new']
                if verdict['status'] == SKIP:
                    credits.append({'student_id': sid, 'name': person['name'], 'message': verdict['detail']})
                elif verdict['status'] == PENDING:
                    pending.append({'student_id': sid, 'name': person['name'], 'issue': verdict['issue'],
                                    'detail': verdict['detail'], 'rows': person['rows'],
                                    'sheets': person['sheets'],
                                    'target': '、'.join(sheet_label(sheets, t) for t in targets)})
            for sheet in sheets:
                target = resolved[sheet['name']]
                if target is None:
                    errors.append({'key': f'{sheet["name"]}:1',
                                   'message': f'“{sheet["name"]}”未匹配业务，请选择目标业务'})
            stats = {'students': len(verdicts),
                     'new_accounts': sum(1 for p in people if verdicts.get(p['student_id'], {}).get('new')),
                     'existing': sum(1 for v in verdicts.values() if not v['new']),
                     'pending': len(pending), 'skipped': len(credits),
                     'memberships': sum(len(v.get('targets') or []) for v in verdicts.values()
                                        if v['status'] != SKIP)}
            result = {'sheets': [{**s, 'target': resolved[s['name']]} for s in sheets], 'rows': rows,
                      'people': [{k: p[k] for k in ('student_id', 'name', 'college', 'sheets', 'rows', 'status',
                                                    'issue', 'detail', 'new', 'targets')} for p in people if 'status' in p],
                      'pending': pending, 'errors': errors, 'credits': credits, 'stats': stats,
                      'new_students': stats['new_accounts'], 'eligible': len([v for v in verdicts.values() if v['status'] == OK]),
                      'skipped': stats['skipped'],
                      'scope': scope or ({'kind': 'GROUP', 'id': resolved[sheets[0]['name']]['group_id']}
                                         if sheets and resolved.get(sheets[0]['name'], {}).get('group_id') else None)}
            if not commit:
                return result
            require(not errors, '预览存在错误，请先修正工作簿或补选业务/小组后重试', 422)
            eligible = [p for p in people if verdicts.get(p['student_id'], {}).get('status') == OK and p.get('targets')]
            require(eligible, '没有可导入的记录，请先确认待处理的行', 422)
            require(not stats['new_accounts'] or initial_password and 8 <= len(initial_password) <= 128,
                    '请填写 8 至 128 字符的新账号初始密码', 422)
            file_hash = hashlib.sha256(raw).hexdigest()
            request_hash = hashlib.sha256(json.dumps({'file': file_hash, 'mappings': resolved,
                                                      'approvals': approvals,
                                                      'skip': sorted(skip_rows)}, sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()
            old = one(c, 'SELECT batch_id FROM member_import WHERE request_hash=%s', (request_hash,))
            if old:
                return {**result, 'replayed': True, 'batch_id': old['batch_id'], 'imported': 0, 'new_accounts': []}
            scoped = scope or next(({'kind': 'GROUP', 'id': t[1]} for p in eligible for t in p['targets'] if t[1]), None)
            if not scoped:
                scoped = next(({'kind': 'BUSINESS', 'id': t[0]} for p in eligible for t in p['targets']), None)
            c.execute('INSERT INTO member_import(file_hash,request_hash,admin_id,created_at,scope_kind,scope_id) '
                      'VALUES(%s,%s,%s,%s,%s,%s)', (file_hash, request_hash, a['_id'], self.clock(),
                                                    scoped['kind'] if scoped else None,
                                                    scoped['id'] if scoped else None))
            batch = c.lastrowid
            day = self.clock().date()
            new_people = [p for p in eligible if p['new']]
            for person in new_people:
                c.execute('INSERT INTO student(student_id,name,college,password_hash) VALUES(%s,%s,%s,%s)',
                          (person['student_id'], person['name'], person['college'],
                           prehashed.get(person['student_id']) or hash_password(initial_password)))
            imported = 0
            for person in eligible:
                sid = person['student_id']
                if not person['new'] and approvals.get(sid) and existing.get(sid, {}).get('status') != 'ACTIVE':
                    c.execute("UPDATE student SET status='ACTIVE' WHERE student_id=%s AND status='QUIT'", (sid,))
                for bid, gid in person['targets']:
                    self._join_business(c, bid, sid, day)
                    if gid:
                        self._join_group(c, gid, sid, day)
                    source = next(r for r in rows if r['student_id'] == sid
                                  and resolved.get(r['sheet']) and resolved[r['sheet']]['business_id'] == bid
                                  and resolved[r['sheet']]['group_id'] == gid
                                  and r['key'] not in skip_rows)
                    c.execute('INSERT INTO member_import_row(batch_id,sheet_name,row_no,student_id,business_id,'
                              'group_id,slot_id,created_account) VALUES(%s,%s,%s,%s,%s,%s,NULL,%s)',
                              (batch, source['sheet'], source['row'], sid, bid, gid,
                               1 if person['new'] else 0))
                    imported += 1
            c.execute('UPDATE member_import SET imported_count=%s,skipped_count=%s WHERE batch_id=%s',
                      (imported, stats['skipped'], batch))
            self.audit(c, a['_id'], 'IMPORT_MEMBERS', 'member_import', batch,
                       after={'imported': imported, 'skipped': stats['skipped'],
                              'new_students': len(new_people)}, reason='名单导入；只建立账号和归属，不计时')
            return {**result, 'batch_id': batch, 'imported': imported,
                    'new_accounts': [{'student_id': p['student_id'], 'name': p['name']} for p in new_people]}

    def member_import_list(self, actor, business_id=None, limit=30):
        """Recent import batches for one business (or all, for a super admin)."""
        from .service import require, require_business_owner
        limit = max(1, min(int(limit or 30), 100))
        with self.db.transaction() as c:
            a = self.actor(c, actor, ('SUPER', 'NORMAL'))
            if a['_role'] != 'SUPER':
                require(business_id, '请先选择业务', 422)
                require_business_owner(c, a, int(business_id), '只能查看本人负责业务的导入记录')
            rows = all_rows(c, '''SELECT i.batch_id,i.created_at,i.scope_kind,i.scope_id,i.imported_count,
                i.skipped_count,i.reverted_at,a.name AS admin_name,
                (SELECT COUNT(*) FROM member_import_row r WHERE r.batch_id=i.batch_id) AS row_count,
                (SELECT GROUP_CONCAT(DISTINCT r.sheet_name SEPARATOR '、') FROM member_import_row r
                    WHERE r.batch_id=i.batch_id) AS sheet_names
                FROM member_import i JOIN admin a ON a.admin_id=i.admin_id
                WHERE (%s IS NULL OR EXISTS(SELECT 1 FROM member_import_row r WHERE r.batch_id=i.batch_id
                    AND r.business_id=%s)) ORDER BY i.created_at DESC,i.batch_id DESC LIMIT %s''',
                        (business_id, business_id, limit))
            return {'business_id': business_id, 'batches': rows}

    def member_import_batch(self, actor, batch_id):
        """Read one import batch, its rows and whether it can still be reverted."""
        from .service import require, require_business_owner
        with self.db.transaction() as c:
            self.actor(c, actor, ('SUPER', 'NORMAL'))
            batch = one(c, 'SELECT * FROM member_import WHERE batch_id=%s', (batch_id,))
            require(batch, '导入批次不存在', 404)
            self._require_revert_rights(c, actor, batch)
            rows = all_rows(c, 'SELECT * FROM member_import_row WHERE batch_id=%s ORDER BY sheet_name,row_no', (batch_id,))
            admins = one(c, 'SELECT name,account FROM admin WHERE admin_id=%s', (batch['admin_id'],))
            reverted = batch.get('reverted_at')
            within = self.clock() - batch['created_at'] <= timedelta(days=7)
            return {'batch_id': batch['batch_id'], 'created_at': batch['created_at'],
                    'admin': admins['name'] if admins else '', 'scope_kind': batch.get('scope_kind'),
                    'scope_id': batch.get('scope_id'), 'imported_count': batch.get('imported_count') or 0,
                    'skipped_count': batch.get('skipped_count') or 0, 'reverted_at': reverted,
                    'revertible': bool(not reverted and within), 'rows': rows,
                    'removed_slots': json.loads(batch.get('removed_slots') or '[]')}

    def _require_revert_rights(self, c, actor, batch):
        from .service import require, require_business_owner
        a = self.actor(c, actor, ('SUPER', 'NORMAL'))
        if a['_role'] == 'SUPER':
            return
        business_ids = {r['business_id'] for r in all_rows(
            c, 'SELECT DISTINCT business_id FROM member_import_row WHERE batch_id=%s', (batch['batch_id'],))}
        require(business_ids, '该批次没有可撤销的归属', 404)
        for business_id in business_ids:
            require_business_owner(c, a, business_id, '只能撤销本人负责业务的导入')

    def revert_member_import(self, actor, batch_id):
        """Undo one batch: remove this batch's memberships, accounts and restore released slots."""
        from .service import require
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER', 'NORMAL'))
            batch = one(c, 'SELECT * FROM member_import WHERE batch_id=%s', (batch_id,))
            require(batch, '导入批次不存在', 404)
            self._require_revert_rights(c, actor, batch)
            require(not batch.get('reverted_at'), '该批次已经撤销', 409)
            require(self.clock() - batch['created_at'] <= timedelta(days=7), '只能撤销最近 7 天内的导入', 422)
            day = batch['created_at'].date()
            rows = all_rows(c, 'SELECT * FROM member_import_row WHERE batch_id=%s', (batch_id,))
            removed = json.loads(batch.get('removed_slots') or '[]')
            accounts, links, restored = [], 0, 0
            for row in rows:
                sid, bid, gid = row['student_id'], row['business_id'], row['group_id']
                if gid and one(c, 'SELECT 1 FROM group_member WHERE group_id=%s AND student_id=%s AND effective_from=%s',
                               (gid, sid, day)):
                    c.execute('DELETE FROM group_member WHERE group_id=%s AND student_id=%s AND effective_from=%s',
                              (gid, sid, day))
                    links += 1
                if bid and one(c, 'SELECT 1 FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from=%s',
                               (bid, sid, day)):
                    c.execute('DELETE FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from=%s',
                              (bid, sid, day))
                    links += 1
                if row.get('slot_id') and one(c, 'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id=%s',
                                              (sid, row['slot_id'])):
                    c.execute('DELETE FROM slot_member WHERE student_id=%s AND slot_id=%s', (sid, row['slot_id']))
                    links += 1
                if row.get('created_account') and sid not in accounts:
                    accounts.append(sid)
            kept = 0
            for sid in accounts:
                remaining = one(c, '''SELECT (SELECT COUNT(*) FROM business_member WHERE student_id=%s)
                    +(SELECT COUNT(*) FROM group_member WHERE student_id=%s)
                    +(SELECT COUNT(*) FROM slot_member WHERE student_id=%s)
                    +(SELECT COUNT(*) FROM admin WHERE student_id=%s) AS n''', (sid, sid, sid, sid))['n']
                if remaining or account_in_use(c, sid):
                    # 已有排班/时长/申请等历史时保留账号，只撤回本次建立的归属
                    kept += 1
                    continue
                c.execute('DELETE FROM student WHERE student_id=%s', (sid,))
            for sid, slot in removed:
                if not one(c, 'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id=%s', (sid, slot)):
                    c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)', (sid, slot))
                    restored += 1
            c.execute('UPDATE member_import SET reverted_at=%s WHERE batch_id=%s', (self.clock(), batch_id))
            summary = {'batch_id': batch_id, 'removed_memberships': links,
                       'removed_accounts': len(accounts) - kept, 'kept_accounts': kept,
                       'restored_slots': restored}
            self.audit(c, a['_id'], 'REVERT_MEMBER_IMPORT', 'member_import', batch_id, after=summary,
                       reason='撤销 Excel 名单导入批次')
            return summary


def person_rows(rows, student_id):
    return [r for r in rows if r['student_id'] == student_id]


def scope_ref(scope):
    """把请求里的 {business_id, group_id} 归一成 {'kind','id'}；已归一的原样返回。"""
    if not scope:
        return None
    if hasattr(scope, 'model_dump'):
        scope = scope.model_dump()
    if scope.get('kind') and scope.get('id'):
        return {'kind': scope['kind'], 'id': int(scope['id'])}
    gid = scope.get('group_id')
    bid = scope.get('business_id') or scope.get('id')
    if gid:
        return {'kind': 'GROUP', 'id': int(gid)}
    if bid:
        return {'kind': 'BUSINESS', 'id': int(bid)}
    return None


def account_in_use(c, student_id):
    """账号是否已被任何外键引用（排班、时长、申请、征集、管理员…）。"""
    tables = [r['TABLE_NAME'] for r in all_rows(c, '''SELECT TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME='student'
          AND REFERENCED_COLUMN_NAME='student_id' AND COLUMN_NAME='student_id'
          AND TABLE_NAME<>'student' ''')]
    for table in tables:
        if one(c, f'SELECT 1 FROM `{table}` WHERE student_id=%s LIMIT 1', (student_id,)):
            return True
    return False



def sheet_label(sheets, target):
    for sheet in sheets:
        if (sheet.get('target') or {}).get('business_id') == target[0] and (sheet.get('target') or {}).get('group_id') == target[1]:
            return f'{sheet["business_name"] or sheet["name"]}·{sheet["group_name"] or "未分组"}'
    return ''
