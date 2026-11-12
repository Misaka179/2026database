"""Core workflows. All writes share one MySQL transaction and writer lock.

Only this layer performs business mutations; API callers cannot supply their role.
Dates/times are Asia/Shanghai. The clock is injectable for deterministic tests.
"""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from .db import Database, one, all_rows
from .security import hash_password, verify_password
from .semester import SemesterService
from .corrections import CorrectionService
from .admin_roles import AdministratorService
from .business import BusinessService
from .leaders import LeaderService


class DomainError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def business_owner_available(c):
    """旧库可能还没有 business.total_manager_admin_id（或整张 business 表），此时退回按时段负责人鉴权。"""
    try:
        return bool(one(c, "SELECT 1 FROM information_schema.COLUMNS WHERE table_schema=DATABASE() AND table_name='business' AND column_name='total_manager_admin_id'"))
    except Exception:
        return False


def business_link_available(c):
    """service_slot.business_id 是业务化改造后的列，旧库没有。"""
    try:
        return bool(one(c, "SELECT 1 FROM information_schema.COLUMNS WHERE table_schema=DATABASE() AND table_name='service_slot' AND column_name='business_id'"))
    except Exception:
        return False


def owner_of_business(c, business_id):
    """业务总负责人：business.total_manager_admin_id 是唯一口径，独立于时段与分队负责人。"""
    if business_id is None or not business_owner_available(c):
        return None
    row = one(c, 'SELECT total_manager_admin_id FROM business WHERE business_id=%s', (business_id,))
    return row['total_manager_admin_id'] if row else None


def require_business_owner(c, a, business_id, message='只能管理本人负责的业务'):
    """超管放行；普通管理员须是业务 total_manager_admin_id。"""
    if a['_role'] == 'SUPER':
        return
    owner = owner_of_business(c, business_id)
    require(a['_role'] == 'NORMAL' and owner is not None and owner == a['_id'], message, 403)


def require(condition, message, status=409):
    if not condition:
        raise DomainError(message, status)


def parse_date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise DomainError('日期格式必须为 YYYY-MM-DD', 422)


def minutes(value):
    if value is None:
        return 0
    if isinstance(value, timedelta):
        return int(value.total_seconds() // 60)
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    try:
        t = time.fromisoformat(value)
        require(t.second == 0 and t.microsecond == 0, '班次时间精确到分钟即可', 422)
        return t.hour * 60 + t.minute
    except (ValueError, TypeError):
        raise DomainError('时间格式必须为 HH:MM', 422)


def instant(day, value):
    return datetime.combine(parse_date(day), time()) + timedelta(minutes=minutes(value))


def reason_text(value):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= 500,
            '原因不能为空且不能超过 500 字', 422)
    return value.strip()


class Service(LeaderService, BusinessService, SemesterService, CorrectionService, AdministratorService):
    def __init__(self, db=None, clock=None):
        self.db = db or Database()
        self.clock = clock or (lambda: datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None))

    def actor(self, c, actor, role=None, active=False):
        kind = actor.get('kind')
        require(kind in ('student', 'admin'), '身份无效', 401)
        table, key = ('student', 'student_id') if kind == 'student' else ('admin', 'admin_id')
        row = one(c, f'SELECT * FROM {table} WHERE {key}=%s', (actor.get('id'),))
        require(row, '账号不存在', 401)
        if kind == 'admin' or active:
            require(row['status'] == 'ACTIVE', '账号已停用或已退队', 403)
        actual_role = 'STUDENT' if kind == 'student' else row['role']
        # Scoped leaders are ordinary administrators.  Preload their slot
        # projection so every existing admin guard can honour it.
        row['_lead_slots'] = []
        if actual_role == 'NORMAL':
            from .leaders import installed as leaders_installed
            if leaders_installed(c):
                row['_lead_slots'] = [s['slot_id'] for s in self.leader_slots(c, row['admin_id'])]
        if role:
            require(actual_role in role, '没有执行此操作的权限', 403)
        row['_kind'], row['_id'], row['_role'] = kind, row[key], actual_role
        return row

    def login(self, kind, account, password):
        require(kind in ('student', 'admin'), '登录类型无效', 422)
        with self.db.transaction() as c:
            table, key = ('student','student_id') if kind == 'student' else ('admin','account')
            row = one(c, f'SELECT * FROM {table} WHERE {key}=%s', (account,))
            require(row and verify_password(password, row['password_hash']), '账号或密码错误', 401)
            # Inactive volunteers retain read access to their historical records.
            require(kind == 'student' or row['status'] == 'ACTIVE', '管理员已停用', 403)
            return {'kind':kind, 'id':row['student_id'] if kind=='student' else row['admin_id']}

    def me(self, actor):
        with self.db.transaction() as c:
            row = self.actor(c, actor, ('SUPER','NORMAL','STUDENT'))
            role = row['_role']
            slot_ids = set()
            total_business_ids = set()
            if role == 'NORMAL':
                slot_ids = {int(s) for s in (row.get('_lead_slots') or [])}
                slot_ids |= {int(s['slot_id']) for s in all_rows(
                    c, 'SELECT slot_id FROM service_slot WHERE manager_admin_id=%s', (row['admin_id'],))}
                if business_owner_available(c):
                    total_business_ids = {int(b['business_id']) for b in all_rows(
                        c, 'SELECT business_id FROM business WHERE total_manager_admin_id=%s', (row['admin_id'],))}
            business_ids = set(total_business_ids)
            if role == 'NORMAL' and slot_ids and business_link_available(c):
                business_ids |= {int(b['business_id']) for b in all_rows(
                    c, 'SELECT DISTINCT business_id FROM service_slot WHERE slot_id IN (' +
                       ','.join(['%s'] * len(slot_ids)) + ')', tuple(sorted(slot_ids)))}
            if role == 'SUPER':
                capabilities = ['overview', 'inbox', 'semesters', 'schedules', 'applications',
                                'collections', 'hours', 'credit', 'basics', 'businesses', 'logs']
            elif role == 'STUDENT':
                capabilities = ['overview', 'inbox', 'schedules', 'applications',
                                'collections', 'hours', 'credit']
            else:
                capabilities = ['overview', 'inbox']
                if slot_ids or total_business_ids:
                    capabilities += ['schedules', 'applications', 'members', 'hours', 'credit']
                if business_ids:
                    capabilities += ['businesses']
                if total_business_ids:
                    capabilities += ['collections']
            payload = {k:v for k,v in row.items() if k != 'password_hash' and not k.startswith('_')}
            payload['role'] = role
            payload['capabilities'] = capabilities
            payload['scope'] = {
                'slot_count': len(slot_ids),
                'business_count': len(business_ids),
                'total_business_count': len(total_business_ids),
                'slot_ids': sorted(slot_ids),
                'business_ids': sorted(business_ids),
                'total_business_ids': sorted(total_business_ids),
            }
            return payload

    def audit(self, c, admin_id, operation, table, target, before=None, after=None, reason=''):
        encode = lambda v: None if v is None else json.dumps(v, ensure_ascii=False, default=str)
        c.execute('''INSERT INTO operation_log
            (admin_id,operation_type,target_table,target_id,before_value,after_value,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (admin_id,operation,table,str(target),encode(before),encode(after),reason))
        log_id=c.lastrowid
        self.notify_audit(c,log_id,operation,table,target,before,after,reason,admin_id)
        if operation in ('CORRECT_ATTENDANCE','RECORD_ATTENDANCE'):
            from .leaders import installed as leaders_installed
            if leaders_installed(c):
                change=one(c,'''SELECT at.schedule_id,s.slot_id,s.student_id,s.schedule_date,st.name AS student_name
                    FROM attendance at JOIN schedule s ON s.schedule_id=at.schedule_id
                    LEFT JOIN student st ON st.student_id=s.student_id
                    WHERE at.attendance_id=%s''',(target,))
                if change:
                    status_label={'NORMAL':'正常','LATE':'迟到','ABSENT':'缺勤','LEAVE':'请假'}.get((after or {}).get('status',''),'已更新')
                    reason_text=(reason or '').strip()
                    reason_note=f'；说明：{reason_text}' if reason_text and not reason_text.isdigit() else ''
                    student=f"{change['student_name']}（{change['student_id']}）" if change['student_name'] else f"学号 {change['student_id']}"
                    message=f"{change['schedule_date']} · {student} · {status_label}{reason_note}"
                    self._notice(c,self.fixed_hour_recipients(c,change['slot_id']),f'leader-attendance:{log_id}',
                                 'SERVICE','考勤已登记',message,'schedules',change['schedule_id'])
        return log_id

    def reset_password(self, actor, kind, account_id, new_password, reason):
        require(kind in ('student','admin'), '账号类型无效',422)
        require(isinstance(new_password,str) and 8<=len(new_password)<=128,'密码长度必须为 8 至 128 个字符',422)
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            if a['_role']=='NORMAL':
                require(kind=='student','普通管理员仅可重置本范围队员密码',403)
                self.leader_membership_guard(c,a,str(account_id))
            table,key=('student','student_id') if kind=='student' else ('admin','admin_id')
            target=one(c,f'SELECT * FROM {table} WHERE {key}=%s FOR UPDATE',(account_id,))
            require(target,'账号不存在',404)
            encoded=hash_password(new_password)
            if kind=='student':
                c.execute('UPDATE student SET password_hash=%s WHERE student_id=%s',(encoded,target['student_id']))
            else:
                c.execute('UPDATE admin SET password_hash=%s WHERE admin_id=%s',(encoded,target['admin_id']))
            self.audit(c,a['_id'],'RESET_PASSWORD',table,target[key],after={
                'account':target['student_id'] if kind=='student' else target['account'],
                'name':target['name']},reason=reason)
            return {'status':'UPDATED','kind':kind}

    def change_password(self, actor, current_password, new_password):
        """Self-service password change for a logged-in student or administrator."""
        with self.db.transaction(True) as c:
            # Students keep read access after leaving, so match the login rule:
            # student status is not re-checked, while a disabled admin is refused.
            # Every role may manage its own password, including scoped LEAD accounts.
            a=self.actor(c,actor,('STUDENT','SUPER','NORMAL','LEAD'))
            linked_id=(a.get('student_id') or a.get('leader_student_id')) if a['_kind']=='admin' else None
            require(current_password != new_password, '密码与原密码一致，请设置不同的新密码', 400)
            actual=one(c,'SELECT password_hash FROM student WHERE student_id=%s',(linked_id,)) if linked_id else a
            require(actual and verify_password(current_password,actual['password_hash']),'当前密码不正确',401)
            require(isinstance(new_password,str) and 8<=len(new_password)<=128,
                    '密码长度必须为 8 至 128 个字符',422)
            encoded=hash_password(new_password)
            if a['_kind']=='student':
                c.execute('UPDATE student SET password_hash=%s WHERE student_id=%s',(encoded,a['_id']))
                # operation_log.admin_id is a required foreign key, so a student
                # cannot be recorded there; leave a trace in the SUPER inbox instead.
                self._notice(c,self._super_recipients(c),
                    f'password-change:student:{a["_id"]}:{self.clock().strftime("%Y%m%d%H%M%S")}',
                    'ACCOUNT','账号密码已修改',
                    f'学号 {a["_id"]} 于 {self.clock().strftime("%Y-%m-%d %H:%M")} 在线修改了密码。',
                    'basics',a['_id'])
                return {'status':'UPDATED'}
            # Administrator accounts are independent from volunteer accounts.
            c.execute('UPDATE admin SET password_hash=%s WHERE admin_id=%s',(encoded,a['_id']))
            self.audit(c,a['_id'],'CHANGE_PASSWORD','admin',a['_id'],
                       after={'account':a.get('account')},reason='本人在线修改密码')
            return {'status':'UPDATED'}

    def request_password_reset(self, kind, account, name, phone='', reason=''):
        """Accept a public reset request; only a matching account notifies SUPERs."""
        require(kind in ('student','admin'),'账号类型无效',422)
        def bounded(value,label,limit,required=False):
            require(isinstance(value,str),f'{label}格式不符合要求',422)
            value=value.strip()
            if required:
                require(value,f'{label}不能为空',422)
            require(len(value)<=limit,f'{label}不能超过 {limit} 个字符',422)
            return value
        account=bounded(account,'账号',64,True)
        name=bounded(name,'姓名',64,True)
        phone=bounded(phone,'手机号',20)
        reason=bounded(reason,'说明',500)
        table,key=('student','student_id') if kind=='student' else ('admin','account')
        with self.db.transaction() as c:
            row=one(c,f'SELECT * FROM {table} WHERE {key}=%s',(account,))
        # The same "accepted" answer is returned for unknown or mismatched accounts,
        # so the public endpoint cannot be used to enumerate accounts.
        if not row or row['name'].strip()!=name:
            return {'status':'ACCEPTED'}
        now=self.clock()
        label='学生' if kind=='student' else '管理员'
        message=(f'账号类型：{label}（{kind}）；账号：{account}；姓名：{row["name"]}；'
                 f'手机号：{phone or "未填写"}；说明：{reason or "未填写"}；'
                 f'申请时间：{now.strftime("%Y-%m-%d %H:%M")}')
        with self.db.transaction(True) as c:
            # One notice per account per calendar day; INSERT IGNORE on the event key dedups.
            self._notice(c,self._super_recipients(c),
                         f'password-reset:{kind}:{account}:{now.date().isoformat()}',
                         'ACCOUNT','密码重置申请',message,'basics',account)
        return {'status':'ACCEPTED'}

    def create_student(self, actor, student_id, name, password, college='', phone=''):
        require(student_id and len(student_id)<=32 and name.strip(), '学号和姓名不能为空', 422)
        encoded = hash_password(password)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            require(not one(c,'SELECT student_id FROM student WHERE student_id=%s',(student_id,)), '学号已存在')
            c.execute('''INSERT INTO student(student_id,name,college,phone,password_hash)
                VALUES(%s,%s,%s,%s,%s)''',(student_id,name.strip(),college,phone,encoded))
            self.audit(c,a['_id'],'CREATE_STUDENT','student',student_id,after={'name':name})
            return {'student_id':student_id}

    def create_admin(self, actor, name, account, password, role='NORMAL'):
        require(role in ('NORMAL','SUPER'), '管理员角色无效', 422)
        encoded = hash_password(password)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('SUPER',))
            require(not one(c,'SELECT admin_id FROM admin WHERE account=%s',(account,)), '账号已存在')
            c.execute('INSERT INTO admin(name,account,password_hash,role) VALUES(%s,%s,%s,%s)',
                      (name,account,encoded,role))
            admin_id = c.lastrowid
            self.audit(c,a['_id'],'CREATE_ADMIN','admin',admin_id,after={'account':account,'role':role})
            return {'admin_id':admin_id}

    def create_slot(self, actor, team_name, period_no, start_time, end_time,
                    need_num, manager_admin_id):
        require(0 <= minutes(start_time) < minutes(end_time) <= 1440, '班次必须在同一天内结束',422)
        require(need_num > 0 and period_no > 0, '人数和时段编号必须为正数',422)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('SUPER',))
            from .fixed_slots import installed
            require(not installed(c), '请在业务管理中为具体固定业务新增时段', 403)
            manager = one(c,"SELECT * FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",(manager_admin_id,))
            require(manager, '负责人必须是启用的普通管理员',422)
            duration = 180 if period_no == 3 else 120
            c.execute('''INSERT INTO service_slot(team_name,period_no,start_time,end_time,
                need_num,service_minutes,manager_admin_id) VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                (team_name,period_no,start_time,end_time,need_num,duration,manager_admin_id))
            slot_id = c.lastrowid
            self.audit(c,a['_id'],'CREATE_SLOT','service_slot',slot_id,after={'team_name':team_name,'period_no':period_no})
            return {'slot_id':slot_id}

    def _legacy_slot(self, c, slot_id):
        row = one(c,'SELECT * FROM service_slot WHERE slot_id=%s',(slot_id,))
        require(row, '班次不存在',404)
        return row

    def _legacy_schedule(self, c, schedule_id):
        row = one(c,'''SELECT s.*,t.manager_admin_id,t.start_time,t.end_time,t.service_minutes,
            t.need_num FROM schedule s
            JOIN service_slot t ON t.slot_id=s.slot_id WHERE s.schedule_id=%s''',(schedule_id,))
        require(row,'排班不存在',404)
        return row

    def scope(self, a, row, daily=False):
        if daily:
            require(a['_role']=='NORMAL', '此日常操作由负责班次的普通管理员执行',403)
        if a['_role']=='SUPER':
            return
        if a['_role']=='NORMAL':
            owner=row.get('business_owner_admin_id', row.get('total_manager_admin_id'))
            require(row.get('manager_admin_id')==a['_id'] or owner is not None and owner==a['_id']
                    or row.get('slot_id') in a.get('_lead_slots',[]),
                    '不能操作其他管理员负责的班次',403)
        else:
            require(row['student_id']==a['_id'], '只能操作本人数据',403)

    def future_schedule(self, row):
        require(row['status']=='ACTIVE', '排班已取消或已完成')
        require(instant(row['schedule_date'],row['start_time']) > self.clock(), '服务已开始，不能再修改申请或排班')

    def available(self, c, student_id, slot_id, day, exclude=None):
        day = parse_date(day)
        student = one(c,'SELECT * FROM student WHERE student_id=%s FOR UPDATE',(student_id,))
        require(student and student['status']=='ACTIVE','志愿者不存在、已停用或已退队')
        slot = self.slot(c,slot_id)
        if slot.get('weekday') is not None:
            from .semester import installed
            calendar = one(c, 'SELECT * FROM semester_day WHERE service_date=%s', (day,)) if installed(c) else None
            weekday = calendar['effective_weekday'] if calendar else day.isoweekday()
            require(weekday is not None, '该日期停工或日历尚未确认，不能安排服务', 422)
            require(weekday==slot['weekday'],'目标日期执行的星期班表必须与所选时段一致',422)
            require(slot['manager_admin_id'] is not None,'该时段尚未分配管理员')
        require(instant(day,slot['start_time']) > self.clock(),'只能安排尚未开始的服务')
        others = all_rows(c,'''SELECT s.*,t.start_time,t.end_time FROM schedule s
            JOIN service_slot t ON s.slot_id=t.slot_id WHERE s.student_id=%s
            AND s.schedule_date=%s AND s.status IN ('ACTIVE','COMPLETED')''',(student_id,day))
        for other in others:
            if other['schedule_id'] == exclude:
                continue
            require(not (minutes(other['start_time']) < minutes(slot['end_time']) and
                         minutes(slot['start_time']) < minutes(other['end_time'])), '目标班次与已有排班时间冲突')
        # 建议人数只用于展示和提示，不再限制手动新增排班。
        return slot

    def create_schedule(self, actor, student_id, slot_id, schedule_date):
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL','SUPER'))
            slot = self.slot(c,slot_id)
            if slot.get('business_id') is not None:self._active_business(c,slot['business_id'])
            self.scope(a,slot)
            require(slot.get('schedule_kind') not in ('WEEKLY','EVENT'),
                    '开心花园按周自动排班；临时业务请使用业务管理入口',422)
            if a['_role']=='NORMAL' and slot.get('weekday') is not None:
                require(one(c,'SELECT student_id FROM slot_member WHERE slot_id=%s AND student_id=%s',
                            (slot_id,student_id)), '只能为本时段队员安排排班',403)
            self.available(c,student_id,slot_id,schedule_date)
            c.execute('INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date) VALUES(%s,%s,%s,%s)',
                      (student_id,slot_id,a['_id'],parse_date(schedule_date)))
            sid = c.lastrowid
            self.audit(c,a['_id'],'CREATE_SCHEDULE','schedule',sid,after={'student_id':student_id,'slot_id':slot_id,'date':schedule_date})
            return {'schedule_id':sid}

    def pending_guard(self, c, schedule_id):
        require(not one(c,"SELECT leave_id FROM leave_application WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(schedule_id,)), '已有待处理或已批准的请假')

    def cancel_schedule(self, actor, schedule_id, reason):
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('NORMAL','SUPER'))
            row=self.schedule(c,schedule_id)
            self.scope(a,row)
            if row['status']=='CANCELLED':
                return {'schedule_id':schedule_id,'status':'CANCELLED','replayed':True}
            self.future_schedule(row)
            c.execute("UPDATE schedule SET status='CANCELLED' WHERE schedule_id=%s",(schedule_id,))
            c.execute("UPDATE schedule SET cancel_reason='MANUAL' WHERE schedule_id=%s",(schedule_id,))
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(schedule_id,))
            self.audit(c,a['_id'],'CANCEL_SCHEDULE','schedule',schedule_id,row,{'status':'CANCELLED'},reason)
            return {'schedule_id':schedule_id,'status':'CANCELLED'}

    def _legacy_apply_leave(self, actor, schedule_id, reason):
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('STUDENT',),True)
            row = self.schedule(c,schedule_id)
            self.scope(a,row)
            self.future_schedule(row)
            self.pending_guard(c,schedule_id)
            c.execute('INSERT INTO leave_application(student_id,schedule_id,reason) VALUES(%s,%s,%s)',(a['_id'],schedule_id,reason))
            return {'leave_id':c.lastrowid}

    def _legacy_approve_leave(self, actor, leave_id, approved):
        desired = 'APPROVED' if approved else 'REJECTED'
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL',))
            app = one(c,'SELECT * FROM leave_application WHERE leave_id=%s FOR UPDATE',(leave_id,))
            require(app,'请假申请不存在',404)
            row = self.schedule(c,app['schedule_id'])
            self.scope(a,row,True)
            if app['approve_status']==desired:
                return {'status':desired,'replayed':True}
            require(app['approve_status']=='PENDING','申请已处理')
            self.future_schedule(row)
            c.execute('UPDATE leave_application SET approve_status=%s,approve_admin_id=%s,approve_time=%s WHERE leave_id=%s',
                      (desired,a['_id'],self.clock(),leave_id))
            self.audit(c,a['_id'],'APPROVE_LEAVE','leave_application',leave_id,app,{'status':desired})
            return {'status':desired}

    def approve_transfer(self, actor, transfer_id, approved, reason=''):
        if not approved:reason=reason_text(reason)
        desired = 'APPROVED' if approved else 'REJECTED'
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL','SUPER'))
            app = one(c,'SELECT * FROM transfer_application WHERE transfer_id=%s FOR UPDATE',(transfer_id,))
            require(app,'换班申请不存在',404)
            return self.approve_fixed_transfer(c,a,app,desired,reason)

    def apply_withdrawal(self, actor, reason):
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('STUDENT',),True)
            require(not one(c,"SELECT withdrawal_id FROM withdrawal_application WHERE student_id=%s AND approve_status='PENDING'",(a['_id'],)),'已有待处理退队申请')
            c.execute('INSERT INTO withdrawal_application(student_id,reason) VALUES(%s,%s)',(a['_id'],reason))
            wid=c.lastrowid
            self.snapshot_withdrawal_leader(c,wid,a['_id'])
            self.notify_application(c,'withdrawal_application',wid)
            return {'withdrawal_id':wid}

    def cancel_future(self, c, student_id, reason='QUIT'):
        from .fixed_slots import installed
        if installed(c):
            c.execute("UPDATE transfer_application SET final_status='CANCELLED' WHERE student_id=%s AND old_slot_id IS NOT NULL AND final_status='PENDING'",(student_id,))
        rows = all_rows(c,"SELECT s.schedule_id,s.schedule_date,t.start_time FROM schedule s JOIN service_slot t ON s.slot_id=t.slot_id WHERE s.student_id=%s AND s.status='ACTIVE'",(student_id,))
        ids = [r['schedule_id'] for r in rows if instant(r['schedule_date'],r['start_time'])>self.clock()]
        for sid in ids:
            c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason=%s WHERE schedule_id=%s",(reason,sid))
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(sid,))
        self.snapshot_memberships(c)
        return ids

    def approve_withdrawal(self, actor, withdrawal_id, approved, reason=''):
        if not approved:reason=reason_text(reason)
        desired = 'APPROVED' if approved else 'REJECTED'
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL','SUPER'))
            app = one(c,'SELECT * FROM withdrawal_application WHERE withdrawal_id=%s FOR UPDATE',(withdrawal_id,))
            require(app,'退队申请不存在',404)
            from .leaders import installed as leaders_installed
            leaders_installed_now=leaders_installed(c)
            if a['_role']=='NORMAL':
                require(self._can_review_withdrawal(c,a,app['student_id']),'该退队申请不属于你的负责范围',403)
            # 超级管理员可兜底审核任意待处理退队申请。
            if app['approve_status']==desired:
                return {'status':desired,'replayed':True}
            require(app['approve_status']=='PENDING','申请已处理')
            cancelled=[]
            if approved:
                self.snapshot_memberships(c)
                c.execute("UPDATE student SET status='QUIT' WHERE student_id=%s",(app['student_id'],))
                cancelled=self.cancel_future(c,app['student_id'])
            c.execute('UPDATE withdrawal_application SET approve_status=%s,admin_id=%s,approve_time=%s WHERE withdrawal_id=%s',
                      (desired,a['_id'],self.clock(),withdrawal_id))
            if leaders_installed_now:
                c.execute('''UPDATE withdrawal_leader_review SET status=%s,admin_id=%s,reason=%s,reviewed_at=%s
                    WHERE withdrawal_id=%s''',(desired,a['_id'],reason,self.clock(),withdrawal_id))
            self.audit(c,a['_id'],'APPROVE_WITHDRAWAL','withdrawal_application',withdrawal_id,app,
                       {'status':desired,'cancelled_schedules':cancelled},reason)
            return {'status':desired,'cancelled_schedules':cancelled}

    def record_attendance(self, actor, schedule_id, status, remark=''):
        require(status in ('NORMAL','LATE','ABSENT','LEAVE'),'考勤状态无效',422)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL','SUPER'))
            row = self.schedule(c,schedule_id)
            self.scope(a,row)
            self.attendance_kind_guard(row,status)
            leave = one(c,"SELECT leave_id FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'",(schedule_id,))
            actual = 'LEAVE' if leave else status
            require(actual != 'LEAVE' or leave,'没有已批准的请假，不能记为请假')
            existing = one(c,'SELECT * FROM attendance WHERE schedule_id=%s',(schedule_id,))
            if existing:
                if existing['attendance_status']==actual:
                    return {'attendance_id':existing['attendance_id'],'status':actual,'replayed':True}
                require(existing.get('source')=='AUTO_WEEKLY' and existing['attendance_status']=='NORMAL'
                        and actual in ('LATE','ABSENT'), '已有不同考勤结果，禁止覆盖已结算考勤')
                reason_text(remark)
            require(row['status']=='ACTIVE' or existing and existing.get('source')=='AUTO_WEEKLY','排班已取消或已完成')
            from .semester import monday
            require(monday(row['schedule_date'])<=self.clock().date() if row.get('schedule_kind')=='WEEKLY'
                    else instant(row['schedule_date'],row['end_time'])<=self.clock(),'班次结束后才能记录考勤')
            if row.get('schedule_kind')=='WEEKLY' and actual=='NORMAL':
                c.execute('UPDATE schedule SET weekly_confirmed=1 WHERE schedule_id=%s',(schedule_id,))
            student = one(c,'SELECT * FROM student WHERE student_id=%s FOR UPDATE',(row['student_id'],))
            if existing:
                aid = existing['attendance_id']
                c.execute("UPDATE attendance SET admin_id=%s,attendance_status=%s,check_time=%s,remark=%s,source='MANUAL',revision=revision+1 WHERE attendance_id=%s",
                          (a['_id'],actual,self.clock(),remark,aid))
                if actual=='ABSENT':
                    c.execute("UPDATE service_record SET service_minutes=0,record_status='VOID' WHERE attendance_id=%s",(aid,))
            else:
                c.execute('''INSERT INTO attendance(schedule_id,admin_id,attendance_status,check_time,remark)
                    VALUES(%s,%s,%s,%s,%s)''',(schedule_id,a['_id'],actual,self.clock(),remark))
                aid = c.lastrowid
            awarded = row['service_minutes'] if actual in ('NORMAL','LATE') else 0
            if actual in ('NORMAL','LATE') and not existing:
                c.execute('INSERT INTO service_record(attendance_id,service_minutes) VALUES(%s,%s)',(aid,awarded))
            before = student['credit_score']
            after = before
            cancelled=[]
            if actual in ('LATE','ABSENT'):
                after=self._penalize(c,row['student_id'],aid,actual,a['_id'],before)
                cancelled=self._set_credit_state(c,student,after)
            c.execute("UPDATE schedule SET status='COMPLETED' WHERE schedule_id=%s",(schedule_id,))
            # Pending applications on an already elapsed occurrence cannot be approved later.
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status='PENDING'",(schedule_id,))
            self.audit(c,a['_id'],'RECORD_ATTENDANCE','attendance',aid,before=existing,after={'status':actual,'minutes':awarded,'credit_before':before,'credit_after':after,'cancelled_schedules':cancelled},reason=remark)
            return {'attendance_id':aid,'status':actual,'service_minutes':awarded,'credit_score':after,'cancelled_schedules':cancelled}

    def revise_hours(self, actor, record_id, service_minutes, reason):
        reason=reason_text(reason)
        require(isinstance(service_minutes,int) and 0<=service_minutes<=1440,'服务分钟数须在 0—1440 之间',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            record=one(c,'SELECT * FROM service_record WHERE record_id=%s FOR UPDATE',(record_id,))
            require(record,'服务记录不存在',404)
            from .hour_units import record_step,validate_half_hour
            if record_step(c,record_id)==30:validate_half_hour(service_minutes)
            c.execute('UPDATE service_record SET service_minutes=%s WHERE record_id=%s',(service_minutes,record_id))
            self.audit(c,a['_id'],'REVISE_HOURS','service_record',record_id,record,{'service_minutes':service_minutes},reason)
            return {'record_id':record_id,'service_minutes':service_minutes}

    def set_rule(self, actor, violation_type, deduct_score, reason):
        reason=reason_text(reason)
        require(violation_type in ('LATE','ABSENT') and 0<=deduct_score<=100,'规则类型或扣分值无效',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            old=one(c,"SELECT * FROM credit_rule WHERE violation_type=%s AND status='ACTIVE'",(violation_type,))
            version=one(c,'SELECT COALESCE(MAX(version),0)+1 AS n FROM credit_rule WHERE violation_type=%s',(violation_type,))['n']
            c.execute("UPDATE credit_rule SET status='RETIRED' WHERE violation_type=%s AND status='ACTIVE'",(violation_type,))
            c.execute('INSERT INTO credit_rule(violation_type,version,deduct_score,create_admin_id) VALUES(%s,%s,%s,%s)',(violation_type,version,deduct_score,a['_id']))
            rid=c.lastrowid
            self.audit(c,a['_id'],'SET_CREDIT_RULE','credit_rule',rid,old,{'version':version,'deduct_score':deduct_score},reason)
            return {'rule_id':rid,'version':version}

    def _legacy_list_slots(self, actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            if a['_role']=='SUPER':
                return all_rows(c,'SELECT * FROM service_slot ORDER BY slot_id')
            slot_ids = {int(s) for s in (a.get('_lead_slots') or [])}
            slot_ids |= {int(s['slot_id']) for s in all_rows(
                c, 'SELECT slot_id FROM service_slot WHERE manager_admin_id=%s', (a['_id'],))}
            if business_owner_available(c) and business_link_available(c):
                owner_slots = all_rows(c, '''SELECT t.slot_id FROM service_slot t JOIN business b ON b.business_id=t.business_id
                    WHERE b.total_manager_admin_id=%s''', (a['_id'],))
                slot_ids |= {int(s['slot_id']) for s in owner_slots}
            if not slot_ids:
                return []
            return all_rows(c,'SELECT * FROM service_slot WHERE slot_id IN (' +
                            ','.join(['%s'] * len(slot_ids)) + ') ORDER BY slot_id', tuple(sorted(slot_ids)))

    def _legacy_list_schedules(self, actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor)
            owner_ok=business_owner_available(c) and business_link_available(c)
            owner_col=',b.total_manager_admin_id AS business_owner_admin_id' if owner_ok else ''
            bid_col=',t.business_id' if business_link_available(c) else ''
            owner_join=' LEFT JOIN business b ON b.business_id=t.business_id' if owner_ok else ''
            sql=f'''SELECT s.*,st.name AS student_name,t.team_name,t.period_no,t.start_time,t.end_time,
                t.manager_admin_id{bid_col}{owner_col},
                at.attendance_status,at.source AS attendance_source,at.revision AS attendance_revision,
                EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') AS leave_approved
                FROM schedule s JOIN service_slot t ON s.slot_id=t.slot_id
                JOIN student st ON st.student_id=s.student_id{owner_join}
                LEFT JOIN attendance at ON at.schedule_id=s.schedule_id'''
            args=()
            if a['_role']=='STUDENT':
                sql+=' WHERE s.student_id=%s'; args=(a['_id'],)
            elif a['_role']=='NORMAL':
                slot_ids = {int(s) for s in (a.get('_lead_slots') or [])}
                slot_ids |= {int(s['slot_id']) for s in all_rows(
                    c, 'SELECT slot_id FROM service_slot WHERE manager_admin_id=%s', (a['_id'],))}
                conditions, extra = [], []
                if slot_ids:
                    conditions.append('t.slot_id IN (' + ','.join(['%s'] * len(slot_ids)) + ')')
                    extra.extend(sorted(slot_ids))
                if owner_ok:
                    business_ids = {int(b['business_id']) for b in all_rows(
                        c, 'SELECT business_id FROM business WHERE total_manager_admin_id=%s',
                        (a['_id'],))}
                    if business_ids:
                        conditions.append('b.business_id IN (' + ','.join(['%s'] * len(business_ids)) + ')')
                        extra.extend(sorted(business_ids))
                if not conditions:
                    return []
                sql += ' WHERE (' + ' OR '.join(conditions) + ')'
                args = tuple(extra)
            return all_rows(c,sql+' ORDER BY s.schedule_date,s.schedule_id',args)

    def _scoped_student_ids(self,c,a):
        """普通负责人可见的队员：时段负责人、业务总负责人及其排班覆盖的人。"""
        if a['_role']=='SUPER':return None
        if a['_role']!='NORMAL':return {a['_id']}
        slot_ids={int(s) for s in (a.get('_lead_slots') or [])}
        slot_ids|={int(s['slot_id']) for s in all_rows(c,'SELECT slot_id FROM service_slot WHERE manager_admin_id=%s',(a['_id'],))}
        business_ids=set()
        if business_owner_available(c):
            business_ids={int(b['business_id']) for b in all_rows(c,'SELECT business_id FROM business WHERE total_manager_admin_id=%s',(a['_id'],))}
        ids=set()
        if slot_ids:
            marks=','.join(['%s']*len(slot_ids))
            ids|={r['student_id'] for r in all_rows(c,f'SELECT DISTINCT student_id FROM slot_member WHERE slot_id IN ({marks})',tuple(sorted(slot_ids)))}
            ids|={r['student_id'] for r in all_rows(c,f'SELECT DISTINCT student_id FROM schedule WHERE slot_id IN ({marks})',tuple(sorted(slot_ids)))}
        if business_ids:
            marks=','.join(['%s']*len(business_ids))
            ids|={r['student_id'] for r in all_rows(c,f'''SELECT DISTINCT student_id FROM business_member WHERE business_id IN ({marks})
                AND effective_from<=CURDATE() AND (effective_until IS NULL OR effective_until>=CURDATE())''',tuple(sorted(business_ids)))}
            ids|={r['student_id'] for r in all_rows(c,f'''SELECT DISTINCT s.student_id FROM schedule s
                JOIN service_slot t ON t.slot_id=s.slot_id WHERE t.business_id IN ({marks})''',tuple(sorted(business_ids)))}
        return ids

    def _legacy_hours(self, actor, student_id=None, start=None, end=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT','SUPER','NORMAL'))
            if a['_role']=='STUDENT':
                sid=a['_id']
                require(not student_id or student_id==sid,'只能查看本人时长',403)
            elif a['_role']=='NORMAL':
                allowed=self._scoped_student_ids(c,a)
                if student_id:
                    require(student_id in allowed,'只能查看本人负责范围内的队员时长',403)
                elif not allowed:
                    return {'student_id':None,'total_minutes':0,'total_hours':0,'records':[]}
                sid=student_id
            else:
                sid=student_id
                require(sid,'请指定学生学号',422)
            require(sid is None or one(c,'SELECT student_id FROM student WHERE student_id=%s',(sid,)),'学生不存在',404)
            sql='''SELECT r.record_id,r.service_minutes,r.record_status,s.schedule_id,
                s.schedule_date,s.slot_id,a.attendance_status FROM service_record r
                JOIN attendance a ON a.attendance_id=r.attendance_id
                JOIN schedule s ON s.schedule_id=a.schedule_id WHERE 1=1'''
            args=[]
            if sid:
                sql+=' AND s.student_id=%s';args.append(sid)
            elif a['_role']=='NORMAL':
                allowed=sorted(allowed)
                sql+=' AND s.student_id IN ('+','.join(['%s']*len(allowed))+')';args.extend(allowed)
            if start:
                sql+=' AND s.schedule_date>=%s'; args.append(parse_date(start))
            if end:
                sql+=' AND s.schedule_date<%s'; args.append(parse_date(end))
            if start and end:
                require(parse_date(start)<parse_date(end),'结束日期须晚于开始日期（结束日期不含当天）',422)
            records=all_rows(c,sql+' ORDER BY s.schedule_date,r.record_id',args)
            total=sum(r['service_minutes'] for r in records if r['record_status']=='VALID')
            return {'student_id':sid,'total_minutes':total,'total_hours':total/60,'records':records}

    def list_applications(self, actor, kind):
        spec={'leave':('leave_application','leave_id','schedule_id'),
              'transfer':('transfer_application','transfer_id',None),
              'withdrawal':('withdrawal_application','withdrawal_id',None)}
        require(kind in spec,'申请类型无效',422)
        table,key,schedule_key=spec[kind]
        with self.db.transaction() as c:
            a=self.actor(c,actor)
            sql=f'SELECT p.* FROM {table} p'; args=()
            if a['_role']=='STUDENT':
                sql+=' WHERE p.student_id=%s'; args=(a['_id'],)
            elif a['_role']=='NORMAL' and kind=='withdrawal':
                pass
            elif a['_role']=='NORMAL':
                from .fixed_slots import installed
                owner_ok=business_owner_available(c) and business_link_available(c)
                owner_join=' LEFT JOIN business b ON b.business_id=t.business_id' if owner_ok else ''
                owner_cond=' OR b.total_manager_admin_id=%s' if owner_ok else ''
                lead_ids=a.get('_lead_slots') or []
                lead_cond=' OR t.slot_id IN ('+','.join(['%s']*len(lead_ids))+')' if lead_ids else ''
                if kind=='transfer' and installed(c):
                    sql+=f' JOIN service_slot t ON t.slot_id=p.old_slot_id{owner_join} WHERE (t.manager_admin_id=%s{owner_cond}{lead_cond})'
                else:
                    sql+=f' JOIN schedule s ON p.{schedule_key}=s.schedule_id JOIN service_slot t ON s.slot_id=t.slot_id{owner_join} WHERE (t.manager_admin_id=%s{owner_cond}{lead_cond})'
                args=[a['_id']]
                if owner_ok: args.append(a['_id'])
                args.extend(lead_ids)
                args=tuple(args)
            rows=all_rows(c,sql+f' ORDER BY p.{key} DESC',args)
            if a['_role']=='NORMAL' and kind=='withdrawal':
                rows=[r for r in rows if self._can_review_withdrawal(c,a,r['student_id'])]
            for row in rows:
                if kind=='withdrawal':
                    from .leaders import installed as leaders_installed
                    if leaders_installed(c):
                        first=one(c,'''SELECT w.status,w.reason,g.admin_id,ad.status AS admin_status
                            FROM withdrawal_leader_review w LEFT JOIN leader_scope g ON g.scope_id=w.scope_id
                            LEFT JOIN admin ad ON ad.admin_id=g.admin_id
                            WHERE w.withdrawal_id=%s''',(row['withdrawal_id'],))
                        row['first_status']=first['status'] if first else 'NOT_REQUIRED'
                        row['first_reason']=first['reason'] if first else ''
                        row['review_reason']=first['reason'] if first else ''
                        row['review_admin_id']=first['admin_id'] if first else None
                        row['requires_first']=bool(first and first['admin_id'] and first['admin_status']=='ACTIVE' and first['status']=='PENDING')
                if kind=='transfer':
                    for prefix in ('old','new'):
                        slot_id=row.get(prefix+'_slot_id')
                        if slot_id:
                            slot=one(c,'SELECT team_name FROM service_slot WHERE slot_id=%s',(slot_id,))
                            row[prefix+'_slot_name']=slot['team_name'] if slot else None
                if a['_role']=='STUDENT':
                    row['can_review']=False
                    continue
                if kind=='transfer':
                    pending=row['final_status']=='PENDING' and row.get('old_slot_id') is not None
                else:
                    pending=row['approve_status']=='PENDING'
                if a['_role']=='NORMAL':
                    row['can_review']=pending and (kind!='withdrawal' or self._can_review_withdrawal(c,a,row['student_id']))
                else:
                    row['can_review']=pending
            return rows

    def credit(self, actor, student_id=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT','SUPER','NORMAL'))
            if a['_role']=='STUDENT':
                require(not student_id or student_id==a['_id'],'只能查看本人信用',403)
                sid=a['_id']
            elif a['_role']=='NORMAL':
                allowed=self._scoped_student_ids(c,a)
                if not student_id:
                    students=all_rows(c,'SELECT student_id,name,college,credit_score,credit_version,status FROM student ORDER BY student_id')
                    return {'students':[s for s in students if s['student_id'] in allowed]}
                require(student_id in allowed,'只能查看本人负责范围内队员的信用',403)
                sid=student_id
            else:
                sid=student_id
                require(sid,'请指定学生',422)
            student=one(c,'SELECT student_id,name,credit_score,credit_version,status FROM student WHERE student_id=%s',(sid,))
            require(student,'学生不存在',404)
            student['logs']=all_rows(c,'SELECT * FROM credit_log WHERE student_id=%s ORDER BY credit_log_id',(sid,))
            return student

    def logs(self, actor, limit=100):
        with self.db.transaction() as c:
            self.actor(c,actor,('SUPER',))
            return all_rows(c,'SELECT * FROM operation_log ORDER BY log_id DESC LIMIT %s',(min(max(limit,1),500),))

    def rules(self, actor):
        with self.db.transaction() as c:
            self.actor(c,actor,('SUPER',))
            return all_rows(c,'SELECT * FROM credit_rule ORDER BY violation_type,version')

    def _legacy_students(self, actor, student_id=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            from .fixed_slots import installed
            fixed=installed(c)
            sql='SELECT st.student_id,st.name,st.college,st.phone,st.credit_score,st.status,st.join_time FROM student st WHERE 1=1'
            args=[]
            if a['_role']=='NORMAL':
                require(fixed,'该管理员尚未配置固定时段',403)
                owner_ok=business_owner_available(c) and business_link_available(c)
                slot_ids = {int(s) for s in (a.get('_lead_slots') or [])}
                slot_ids |= {int(s['slot_id']) for s in all_rows(
                    c, 'SELECT slot_id FROM service_slot WHERE manager_admin_id=%s', (a['_id'],))}
                business_ids = set()
                if owner_ok:
                    business_ids = {int(b['business_id']) for b in all_rows(
                        c, 'SELECT business_id FROM business WHERE total_manager_admin_id=%s',
                        (a['_id'],))}
                scope_conditions, scope_args = [], []
                if slot_ids:
                    scope_conditions.append('t.slot_id IN (' + ','.join(['%s'] * len(slot_ids)) + ')')
                    scope_args.extend(sorted(slot_ids))
                if business_ids:
                    scope_conditions.append('b.business_id IN (' + ','.join(['%s'] * len(business_ids)) + ')')
                    scope_args.extend(sorted(business_ids))
                if not scope_conditions:
                    sql += ' AND 1=0'
                else:
                    owner_join = ' LEFT JOIN business b ON b.business_id=t.business_id' if owner_ok else ''
                    sql += f" AND EXISTS(SELECT 1 FROM slot_member m JOIN service_slot t ON m.slot_id=t.slot_id{owner_join} WHERE m.student_id=st.student_id AND (" + ' OR '.join(scope_conditions) + '))'
                    args.extend(scope_args)
            if student_id:
                sql+=' AND st.student_id=%s';args.append(student_id)
            rows=list(all_rows(c,sql+' ORDER BY st.student_id',args))
            for row in rows:
                row['slots']=[]
            if fixed and rows:
                owner_ok=business_owner_available(c) and business_link_available(c)
                owner_col=',b.total_manager_admin_id AS business_owner_admin_id' if owner_ok else ''
                owner_join=' LEFT JOIN business b ON b.business_id=t.business_id' if owner_ok else ''
                links=all_rows(c,f'''SELECT m.student_id,m.slot_id,t.team_name,t.manager_admin_id{owner_col} FROM slot_member m
                    JOIN service_slot t ON t.slot_id=m.slot_id{owner_join}''')
                by_id={r['student_id']:r for r in rows}
                lead_slot_ids={int(s) for s in (a.get('_lead_slots') or [])}
                for link in links:
                    if link['student_id'] in by_id and (a['_role']=='SUPER' or link['manager_admin_id']==a['_id'] or int(link['slot_id']) in lead_slot_ids or owner_ok and link['business_owner_admin_id']==a['_id']):
                        by_id[link['student_id']]['slots'].append({'slot_id':link['slot_id'],'name':link['team_name'],'team_name':link['team_name']})
            return rows

    def configure_slot(self, actor, slot_id, manager_admin_id, need_num):
        require(need_num is None or isinstance(need_num,int) and 1<=need_num<=10000,'建议人数必须为 1 至 10000，或留空待设置',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            before=self.slot(c,slot_id)
            if a['_role']=='NORMAL':
                require_business_owner(c,a,before['business_id'])
            require(before.get('weekday') is not None or before.get('schedule_kind')=='WEEKLY','只能设置固定时段或按周岗位',422)
            if manager_admin_id is not None:
                require(one(c,"SELECT admin_id FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",(manager_admin_id,)), '负责人须为有效普通管理员',422)
                from .leaders import require_no_other_assignment
                require_no_other_assignment(c, manager_admin_id, 'service_slot', slot_id)
            # 建议人数只是展示参考值，不限制新增排班、换班或后续设置。
            c.execute('UPDATE service_slot SET manager_admin_id=%s,need_num=%s WHERE slot_id=%s',(manager_admin_id,need_num,slot_id))
            self.audit(c,a['_id'],'CONFIGURE_SLOT','service_slot',slot_id,
                       {'manager_admin_id':before['manager_admin_id'],'need_num':before['need_num']},
                       {'manager_admin_id':manager_admin_id,'need_num':need_num})
            self.sync_semesters(c)
            return {'slot_id':slot_id}

    def _legacy_set_memberships(self, actor, student_id, slot_ids):
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            require(one(c,'SELECT student_id FROM student WHERE student_id=%s',(student_id,)),'学号不存在',404)
            for sid in set(slot_ids):
                require(self.slot(c,sid).get('weekday') is not None,'请选择固定时段',422)
            before=all_rows(c,'SELECT slot_id FROM slot_member WHERE student_id=%s',(student_id,))
            self.snapshot_memberships(c)
            c.execute('DELETE FROM slot_member WHERE student_id=%s',(student_id,))
            for sid in set(slot_ids):
                c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(student_id,sid))
            c.execute("""UPDATE transfer_application p SET final_status='CANCELLED'
                WHERE p.student_id=%s AND p.old_slot_id IS NOT NULL AND p.final_status='PENDING'
                AND NOT EXISTS
                (SELECT 1 FROM slot_member m WHERE m.student_id=p.student_id AND m.slot_id=p.old_slot_id)""",(student_id,))
            self.audit(c,a['_id'],'SET_MEMBERSHIPS','student',student_id,{'slots':[x['slot_id'] for x in before]},{'slots':slot_ids})
            self.sync_semesters(c)
            return {'student_id':student_id,'slot_ids':slot_ids}

    def my_memberships(self, actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT',))
            from .fixed_slots import installed
            if not installed(c):
                return []
            return list(all_rows(c,'''SELECT t.*,ad.name AS manager_name FROM slot_member m
                JOIN service_slot t ON t.slot_id=m.slot_id
                LEFT JOIN admin ad ON ad.admin_id=t.manager_admin_id
                WHERE m.student_id=%s ORDER BY t.weekday,t.period_no''',(a['_id'],)))

    def fixed_transfer_check(self, c, student_id, old_slot_id, new_slot_id):
        student=one(c,'SELECT status FROM student WHERE student_id=%s',(student_id,))
        require(student and student['status']=='ACTIVE','队员已停用或已退队')
        require(one(c,'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id=%s',
                    (student_id,old_slot_id)),'原固定班次已不属于该队员，请刷新后重新申请')
        old=self.slot(c,old_slot_id)
        target=self.slot(c,new_slot_id)
        if target.get('business_id') is not None:self._active_business(c,target['business_id'])
        require(old.get('weekday') is not None or old.get('schedule_kind')=='WEEKLY','原固定班次不支持换班')
        require(target.get('weekday') is not None or target.get('schedule_kind')=='WEEKLY','请选择有效的固定班次',422)
        require(old_slot_id!=new_slot_id,'目标与原固定班次相同')
        require(old.get('business_id')==target.get('business_id'),'跨业务调整请联系超级管理员',422)
        others=all_rows(c,'''SELECT t.* FROM slot_member m JOIN service_slot t ON m.slot_id=t.slot_id
            WHERE m.student_id=%s AND m.slot_id<>%s''',(student_id,old_slot_id))
        if target.get('business_code')=='CONSULT':
            remaining={r['weekday'] for r in others if r.get('business_id')==target['business_id']}
            desired_days=remaining|{target['weekday']};previous_days=remaining|{old['weekday']}
            require(len(desired_days)<=1 or len(previous_days)>1 and desired_days<=previous_days,
                    '咨询服务队员只能属于一个分队，请联系全局超管统一调整归属',422)
        for other in others:
            require(other['slot_id']!=new_slot_id,'你已属于目标固定班次')
            if other.get('weekday')==target['weekday']:
                require(not (minutes(other['start_time'])<minutes(target['end_time']) and
                             minutes(target['start_time'])<minutes(other['end_time'])),'目标班次与已有固定班次时间冲突')
        # 建议人数只是参考值，不作为换班通过或拒绝的门槛；目标时段负责人也仅用于提示，不阻塞审批。
        return old

    def apply_fixed_transfer(self, actor, old_slot_id, new_slot_id, reason):
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('STUDENT',),True)
            self.fixed_transfer_check(c,a['_id'],old_slot_id,new_slot_id)
            require(not one(c,"""SELECT 1 FROM transfer_application WHERE student_id=%s
                AND old_slot_id=%s AND final_status='PENDING'""",
                (a['_id'],old_slot_id)),'该固定班次已有待处理的换班申请')
            c.execute('''INSERT INTO transfer_application(student_id,old_slot_id,new_slot_id,reason)
                VALUES(%s,%s,%s,%s)''',(a['_id'],old_slot_id,new_slot_id,reason))
            tid=c.lastrowid
            self.notify_application(c,'transfer_application',tid)
            return {'transfer_id':tid}

    def approve_fixed_transfer(self, c, actor, app, desired, reason=''):
        old=self.slot(c,app['old_slot_id'])
        if actor['_role']=='NORMAL':
            self.scope(actor,old,True)
        # 超级管理员可兜底审核任意待处理申请，不要求原时段没有普通审核人。
        if app['final_status']==desired:
            return {'status':desired,'replayed':True}
        require(app['final_status']=='PENDING','申请已处理或已取消')
        if desired=='APPROVED':
            self.fixed_transfer_check(c,app['student_id'],app['old_slot_id'],app['new_slot_id'])
            self.snapshot_memberships(c)
            c.execute('DELETE FROM slot_member WHERE student_id=%s AND slot_id=%s',(app['student_id'],app['old_slot_id']))
            c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(app['student_id'],app['new_slot_id']))
            self.sync_semesters(c, strict_student=app['student_id'])
        c.execute('''UPDATE transfer_application
            SET final_status=%s,final_admin_id=%s,final_time=%s
            WHERE transfer_id=%s''',(desired,actor['_id'],self.clock(),app['transfer_id']))
        self.audit(c,actor['_id'],'TRANSFER_REVIEW','transfer_application',app['transfer_id'],app,
                   {'status':desired,'old_slot_id':app['old_slot_id'],'new_slot_id':app['new_slot_id']},
                   reason or '每周固定班次调整')
        return {'status':desired,'fixed_membership_updated':desired=='APPROVED'}

    def _slot_conflict(self,c,student_id,previous,target_ids):
        """Return (slots to release, message) when a fixed-business join conflicts."""
        def valid(ids):
            self._validate_memberships(c,student_id,ids);return True
        try:
            valid(previous+target_ids);return (None,'')
        except DomainError as exc:
            message=exc.message
        for slot in sorted(set(previous)):
            try:
                valid([s for s in previous if s!=slot]+target_ids);return ([slot],message)
            except DomainError:
                pass
        return (sorted(set(previous)),message)

    def import_roster(self, actor, file_base64, sheet_name=None, map_categories=True,
                      commit=False, initial_password=None, accept_warnings=False,
                      business_id=None, slot_id=None, approvals=None):
        """固定业务名单导入：三级页传 slot_id 时全员归该时段，忽略「分类」列。"""
        from .roster import parse_workbook
        from .import_common import OK, PENDING, SKIP, evaluate
        approvals={str(k):bool(v) for k,v in (approvals or {}).items()}
        with self.db.transaction() as c:
            self.actor(c,actor,('SUPER','NORMAL'))
            # need_num 仅作为建议人数；名单导入只校验业务、时段和归属冲突，不校验容量。
            slot=one(c,'SELECT * FROM service_slot WHERE slot_id=%s',(slot_id,)) if slot_id else None
            if slot_id:
                require(slot and slot['weekday'],'请选择有效的固定时段',422)
                business_id=business_id or slot['business_id']
            biz=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,)) if business_id else None
            force_pair=(slot['weekday'],slot['period_no']) if slot else None
        try:
            preview=parse_workbook(file_base64,sheet_name,map_categories,force_pair,
                                   business_name=(biz['name'] if biz else None))
        except Exception as exc:
            if isinstance(exc,ValueError):raise DomainError(str(exc),422) from exc
            raise DomainError('无法读取该工作簿，请检查是否为有效的 .xlsx 文件',422) from exc
        prehashed={}
        if commit:
            # 密码哈希很慢（PBKDF2 60 万轮），先只读完成权限校验并确认要建号的人，在写锁外算完再进事务
            with self.db.transaction() as c0:
                a0=self.actor(c0,actor,('SUPER','NORMAL'))
                from .business_schema import installed as business_installed
                if business_installed(c0):
                    biz0=one(c0,'SELECT * FROM business WHERE business_id=%s',(business_id,)) if business_id else one(c0,"SELECT * FROM business WHERE code='CONSULT'")
                    require(biz0 and biz0['kind']=='FIXED','请选择咨询服务、美育或青广宣传；专项时长使用专项导入',422)
                    require_business_owner(c0,a0,biz0['business_id'],'只能管理本人负责业务的名单')
                existing_ids={r['student_id'] for r in all_rows(c0,'SELECT student_id FROM student')}
                missing=[p['student_id'] for p in preview['students'] if p['student_id'] not in existing_ids]
            if missing:
                require(initial_password and 8<=len(initial_password)<=128,'请设置 8 至 128 字符的新队员初始密码',422)
                digest=hash_password(initial_password)
                prehashed={sid:digest for sid in missing}
        with self.db.transaction(commit) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            from .business_schema import installed as business_installed
            multi=business_installed(c)
            if multi:
                biz=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,)) if business_id else one(c,"SELECT * FROM business WHERE code='CONSULT'")
                require(biz and biz['kind']=='FIXED','请选择咨询服务、美育或青广宣传；专项时长使用专项导入',422)
                require_business_owner(c,a,biz['business_id'],'只能管理本人负责业务的名单')
                slots=all_rows(c,'SELECT slot_id,weekday,period_no FROM service_slot WHERE business_id=%s AND weekday IS NOT NULL',(biz['business_id'],))
                preview['business_name']=biz['name']
            else:
                slots=all_rows(c,'SELECT slot_id,weekday,period_no FROM service_slot WHERE weekday IS NOT NULL')
            mapping={(s['weekday'],s['period_no']):s['slot_id'] for s in slots}
            business_label=(biz['name'] if biz else preview.get('business_name') or '当前业务')
            day_nums=sorted({int(s['weekday']) for s in slots})
            period_nums=sorted({int(s['period_no']) for s in slots})
            days_text=('周一至周日' if day_nums==[1,2,3,4,5,6,7] else '、'.join(f'周{"一二三四五六日"[d-1]}' for d in day_nums)) or '无可用星期'
            periods_text=(f'第{period_nums[0]}—{period_nums[-1]}时段' if period_nums and period_nums==list(range(period_nums[0],period_nums[-1]+1)) else '、'.join(f'第{p}时段' for p in period_nums)) or '无可用时段'
            allowed_hint=f'{days_text} {periods_text}'
            existing={r['student_id']:r for r in all_rows(c,'SELECT * FROM student')}
            slot_members={}
            for r in all_rows(c,'SELECT student_id,slot_id FROM slot_member'):
                slot_members.setdefault(r['student_id'],set()).add(r['slot_id'])
            people=preview['students'];errors=[];pending=[];release={}
            for person in people:
                sid=person['student_id']
                verdict=evaluate(person,existing.get(sid),approvals.get(sid))
                person.update({'status':verdict['status'],'issue':verdict['issue'],'detail':verdict['detail'],
                               'new':verdict['new'],'slots':[tuple(p) for p in person['slots']]})
                if not all(pair in mapping for pair in person['slots']):
                    bad=[pair for pair in person['slots'] if pair not in mapping]
                    bad_text='、'.join(f'周{"一二三四五六日"[d-1]}第{p}时段' for d,p in bad)
                    errors.append({'row':person['rows'][0],'student_id':sid,'name':person['name'],
                                   'message':f'第 {person["rows"][0]} 行 {person["name"]}（{sid}）的时段“{bad_text}”在“{business_label}”中不存在；本业务可用时段为 {allowed_hint}。请核对表格的「分类」列。'});continue
                target=[mapping[pair] for pair in person['slots']]
                if verdict['status']==SKIP or not target:continue
                previous=list(slot_members.get(sid,()))
                need,message=self._slot_conflict(c,sid,previous,target)
                if not need:continue
                release[sid]=need
                if approvals.get(sid):
                    person.update({'detail':message,'status':OK,'issue':None})
                else:
                    person.update({'status':PENDING,'issue':'slot','detail':message})
            preview['errors']=errors
            for person in people:
                if person['status']==PENDING:
                    pending.append({'student_id':person['student_id'],'name':person['name'],
                                    'issue':person['issue'],'detail':person['detail'],
                                    'rows':person['rows'],'sheets':person['sheets'],
                                    'target':', '.join(f'周{"一二三四五六日"[d-1]}-第{p}时段' for d,p in person['slots']) or '仅建账号'})
            credits=[{'student_id':p['student_id'],'name':p['name'],'message':p['detail']}
                     for p in people if p['status']==SKIP]
            stats={'students':len(people),'new_accounts':sum(1 for p in people if p.get('new')),
                   'existing':sum(1 for p in people if not p.get('new')),
                   'pending':len(pending),'skipped':len(preview.get('skipped',[]))+len(credits),
                   'memberships':sum(len(p['slots']) for p in people if p['status']!=SKIP)}
            preview.update({'pending':pending,'stats':stats,'credits':credits,
                            'target_slot':({'slot_id':slot['slot_id'],'label':f'周{"一二三四五六日"[slot["weekday"]-1]}-第{slot["period_no"]}时段'} if slot else None),
                            'scope':({'kind':'SLOT','id':slot['slot_id']} if slot else ({'kind':'BUSINESS','id':biz['business_id']} if biz else None)),
                            'new_students':stats['new_accounts'],'existing_students':stats['existing'],
                            'unique_students':len(people),'memberships':stats['memberships']})
            if not commit:return preview
            require(not errors,'预览存在错误，请先修正工作簿后重试',422)
            importable=[p for p in people if p['status']==OK]
            require(importable,'没有可导入的记录，请先确认待处理的行',422)
            require(not stats['new_accounts'] or initial_password and 8<=len(initial_password)<=128,'请设置 8 至 128 字符的新队员初始密码',422)
            require(mapping,'固定时段尚未初始化')
            file_hash=hashlib.sha256(file_base64.encode()).hexdigest()
            request_hash=hashlib.sha256(json.dumps({'file':file_hash,'business':business_id,'slot':slot_id,
                'approvals':approvals},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            old=one(c,'SELECT batch_id FROM member_import WHERE request_hash=%s',(request_hash,))
            if old:
                return {'replayed':True,'batch_id':old['batch_id'],'new_students':0,'existing_students':0,
                        'added_memberships':0,'pending':len(pending),'skipped':stats['skipped']}
            c.execute('INSERT INTO member_import(file_hash,request_hash,admin_id,created_at,scope_kind,scope_id) VALUES(%s,%s,%s,%s,%s,%s)',
                      (file_hash,request_hash,a['_id'],self.clock(),'SLOT' if slot else 'BUSINESS',
                       slot['slot_id'] if slot else (biz['business_id'] if biz else None)))
            batch=c.lastrowid;added=0;removed=[]
            self.snapshot_memberships(c)
            new_accounts=[];reactivate=[];deletions=[];insertions=[];import_rows=[]
            for person in importable:
                sid=person['student_id']
                if person.get('new'):
                    new_accounts.append((sid,person['name'],person['college'],prehashed.get(sid) or hash_password(initial_password)))
                elif approvals.get(sid) and existing.get(sid) and existing[sid]['status']!='ACTIVE':
                    reactivate.append((sid,))
                current=set(slot_members.get(sid,()))
                for slot_to_release in release.get(sid,[]) or []:
                    if slot_to_release in current:
                        current.discard(slot_to_release);deletions.append((sid,slot_to_release))
                        removed.append([sid,slot_to_release])
                for slot_to_add in [mapping[pair] for pair in person['slots']]:
                    if slot_to_add not in current:
                        current.add(slot_to_add);insertions.append((sid,slot_to_add));added+=1
                slot_members[sid]=current
                sheet,number=person['keys'][0].rsplit(':',1)
                import_rows.append((batch,sheet,int(number),sid,biz['business_id'],
                    (mapping[person['slots'][0]] if person['slots'] else (slot['slot_id'] if slot else None)),
                    1 if person.get('new') else 0))
            if new_accounts:c.executemany('INSERT INTO student(student_id,name,college,password_hash) VALUES(%s,%s,%s,%s)',new_accounts)
            if reactivate:c.executemany("UPDATE student SET status='ACTIVE' WHERE student_id=%s AND status='QUIT'",reactivate)
            if deletions:c.executemany('DELETE FROM slot_member WHERE student_id=%s AND slot_id=%s',deletions)
            if insertions:c.executemany('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',insertions)
            if import_rows:c.executemany('INSERT INTO member_import_row(batch_id,sheet_name,row_no,student_id,business_id,group_id,slot_id,created_account) VALUES(%s,%s,%s,%s,%s,NULL,%s,%s)',import_rows)
            c.execute('UPDATE member_import SET imported_count=%s,skipped_count=%s,removed_slots=%s WHERE batch_id=%s',
                      (len(importable),stats['skipped'],json.dumps(removed,ensure_ascii=False),batch))
            summary={'new_students':stats['new_accounts'],'existing_students':max(stats['existing']-stats['skipped'],0),
                     'added_memberships':added,'batch_id':batch,'pending':len(pending),'skipped':stats['skipped']}
            self.audit(c,a['_id'],'IMPORT_ROSTER','member_import',batch,after=summary,reason='Excel 队员导入；只建立账号和归属，不计时')
            if (added or removed) and one(c,'SELECT 1 FROM semester LIMIT 1'):self.sync_semesters(c)
            return summary
