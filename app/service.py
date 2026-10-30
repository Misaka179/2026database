"""Core workflows. All writes share one MySQL transaction and writer lock.

Only this layer performs business mutations; API callers cannot supply their role.
Dates/times are Asia/Shanghai. The clock is injectable for deterministic tests.
"""
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
        if kind == 'admin' and (row.get('student_id') or row.get('leader_student_id')):
            linked = one(c, 'SELECT status FROM student WHERE student_id=%s', (row.get('student_id') or row.get('leader_student_id'),))
            require(linked and linked['status']=='ACTIVE', '关联队员已停用或退队，管理员权限暂停', 403)
        actual_role = 'STUDENT' if kind == 'student' else row['role']
        # New scoped role is deny-by-default for all legacy endpoints.
        if actual_role == 'LEAD':
            require(role and 'LEAD' in role, '该功能未授权给分队／美育负责人', 403)
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
            linked_id = (row.get('student_id') or row.get('leader_student_id')) if row and kind=='admin' else None
            linked = one(c,'SELECT password_hash,status FROM student WHERE student_id=%s',(linked_id,)) if linked_id else None
            require(row and verify_password(password, (linked or row)['password_hash']), '账号或密码错误', 401)
            # Inactive volunteers retain read access to their historical records.
            require(kind == 'student' or row['status'] == 'ACTIVE', '管理员已停用', 403)
            require(not linked or linked['status']=='ACTIVE', '关联队员已停用或退队，管理员权限暂停', 403)
            return {'kind':kind, 'id':row['student_id'] if kind=='student' else row['admin_id']}

    def me(self, actor):
        with self.db.transaction() as c:
            row = self.actor(c, actor, ('SUPER','NORMAL','STUDENT','LEAD'))
            return {k:v for k,v in row.items() if k != 'password_hash' and not k.startswith('_')}

    def audit(self, c, admin_id, operation, table, target, before=None, after=None, reason=''):
        encode = lambda v: None if v is None else json.dumps(v, ensure_ascii=False, default=str)
        c.execute('''INSERT INTO operation_log
            (admin_id,operation_type,target_table,target_id,before_value,after_value,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (admin_id,operation,table,str(target),encode(before),encode(after),reason))
        log_id=c.lastrowid
        self.notify_audit(c,log_id,operation,table,target,before,after,reason)
        if operation in ('CORRECT_ATTENDANCE','RECORD_ATTENDANCE'):
            from .leaders import installed as leaders_installed
            if leaders_installed(c):
                change=one(c,'''SELECT s.slot_id,s.student_id,s.schedule_date FROM attendance at JOIN schedule s ON s.schedule_id=at.schedule_id WHERE at.attendance_id=%s''',(target,))
                if change:
                    self._notice(c,self.fixed_hour_recipients(c,change['slot_id']),f'leader-attendance:{log_id}',
                                 'SERVICE','考勤记录已更新',f"学号 {change['student_id']}，{change['schedule_date']}：{(after or {}).get('status','')}。{reason}。日报保留生成时快照，请查看最新记录。",'schedules',target)
        return log_id

    def reset_password(self, actor, kind, account_id, new_password, reason):
        require(kind in ('student','admin'), '账号类型无效',422)
        require(isinstance(new_password,str) and 8<=len(new_password)<=128,'密码长度必须为 8 至 128 个字符',422)
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','LEAD'))
            if a['_role']=='LEAD':
                require(kind=='student','负责人仅可重置本范围队员密码',403)
                self.leader_membership_guard(c,a,str(account_id))
            table,key=('student','student_id') if kind=='student' else ('admin','admin_id')
            target=one(c,f'SELECT * FROM {table} WHERE {key}=%s FOR UPDATE',(account_id,))
            require(target,'账号不存在',404)
            student_id=target['student_id'] if kind=='student' else target.get('student_id') or target.get('leader_student_id')
            encoded=hash_password(new_password)
            if student_id:
                require(one(c,'SELECT student_id FROM student WHERE student_id=%s FOR UPDATE',(student_id,)), '关联队员不存在',404)
                c.execute('UPDATE student SET password_hash=%s WHERE student_id=%s',(encoded,student_id))
                c.execute('UPDATE admin SET password_hash=%s WHERE student_id=%s',(encoded,student_id))
            else:
                c.execute('UPDATE admin SET password_hash=%s WHERE admin_id=%s',(encoded,target['admin_id']))
            self.audit(c,a['_id'],'RESET_PASSWORD',table,target[key],after={
                'account':target['student_id'] if kind=='student' else target['account'],
                'name':target['name'],'student_id':student_id},reason=reason)
            return {'status':'UPDATED','linked_student_id':student_id}

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

    def create_slot(self, actor, team_name, period_no, start_time, end_time, location,
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
            c.execute('''INSERT INTO service_slot(team_name,period_no,start_time,end_time,location,
                need_num,service_minutes,manager_admin_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                (team_name,period_no,start_time,end_time,location,need_num,duration,manager_admin_id))
            slot_id = c.lastrowid
            self.audit(c,a['_id'],'CREATE_SLOT','service_slot',slot_id,after={'team_name':team_name,'period_no':period_no})
            return {'slot_id':slot_id}

    def _legacy_slot(self, c, slot_id):
        row = one(c,'SELECT * FROM service_slot WHERE slot_id=%s',(slot_id,))
        require(row, '班次不存在',404)
        return row

    def _legacy_schedule(self, c, schedule_id):
        row = one(c,'''SELECT s.*,t.manager_admin_id,t.start_time,t.end_time,t.service_minutes,
            t.need_num,t.status AS slot_status FROM schedule s
            JOIN service_slot t ON t.slot_id=s.slot_id WHERE s.schedule_id=%s''',(schedule_id,))
        require(row,'排班不存在',404)
        return row

    def scope(self, a, row, daily=False):
        if a['_role']=='LEAD':
            require(not daily and row['slot_id'] in a.get('_lead_slots',[]),'不属于你的管理范围',403)
            return
        if daily:
            require(a['_role']=='NORMAL', '此日常操作由负责班次的普通管理员执行',403)
        if a['_role']=='SUPER':
            return
        if a['_role']=='NORMAL':
            require(row['manager_admin_id']==a['_id'], '不能操作其他管理员负责的班次',403)
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
        require(slot['status']=='ACTIVE','目标班次已停用')
        if slot.get('weekday') is not None:
            from .semester import installed
            calendar = one(c, 'SELECT * FROM semester_day WHERE service_date=%s', (day,)) if installed(c) else None
            weekday = calendar['effective_weekday'] if calendar else day.isoweekday()
            require(weekday is not None, '该日期停工或日历尚未确认，不能安排服务', 422)
            require(weekday==slot['weekday'],'目标日期执行的星期班表必须与所选时段一致',422)
            require(slot['manager_admin_id'] is not None,'该时段尚未分配管理员')
            require(slot['need_num'] is not None,'该时段尚未设置人数上限')
        require(instant(day,slot['start_time']) > self.clock(),'只能安排尚未开始的服务')
        others = all_rows(c,'''SELECT s.*,t.start_time,t.end_time FROM schedule s
            JOIN service_slot t ON s.slot_id=t.slot_id WHERE s.student_id=%s
            AND s.schedule_date=%s AND s.status IN ('ACTIVE','COMPLETED')''',(student_id,day))
        for other in others:
            if other['schedule_id'] == exclude:
                continue
            require(not (minutes(other['start_time']) < minutes(slot['end_time']) and
                         minutes(slot['start_time']) < minutes(other['end_time'])), '目标班次与已有排班时间冲突')
        count = one(c,"SELECT COUNT(*) AS n FROM schedule WHERE slot_id=%s AND schedule_date=%s AND status IN ('ACTIVE','COMPLETED') AND (%s IS NULL OR schedule_id<>%s)",
                    (slot_id,day,exclude,exclude))['n']
        require(count < slot['need_num'],'目标日期的班次人数已满')
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
        require(not one(c,"SELECT transfer_id FROM transfer_application WHERE old_schedule_id=%s AND first_status<>'REJECTED' AND final_status='PENDING'",(schedule_id,)), '已有待处理的换班申请')

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
            c.execute("UPDATE transfer_application SET final_status='CANCELLED' WHERE old_schedule_id=%s AND final_status='PENDING' AND first_status<>'REJECTED'",(schedule_id,))
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

    def apply_transfer(self, actor, old_schedule_id, new_slot_id, new_date, reason):
        with self.db.transaction() as c:
            self.actor(c,actor,('STUDENT',),True)
        raise DomainError('不再支持单次换班，请申请长期更换每周固定时段', 410)

    def approve_transfer(self, actor, transfer_id, stage, approved):
        require(stage in ('first','final'),'审批阶段无效',422)
        desired = 'APPROVED' if approved else 'REJECTED'
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL',) if stage=='first' else ('SUPER',))
            app = one(c,'SELECT * FROM transfer_application WHERE transfer_id=%s FOR UPDATE',(transfer_id,))
            require(app,'换班申请不存在',404)
            if app.get('old_slot_id') is not None:
                return self.approve_fixed_transfer(c,a,app,stage,desired)
            raise DomainError('单次换班已停用，历史申请不能继续审批，请重新申请长期换时段', 410)

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
            c.execute("UPDATE transfer_application SET final_status='CANCELLED' WHERE student_id=%s AND old_slot_id IS NOT NULL AND final_status='PENDING' AND first_status<>'REJECTED'",(student_id,))
        rows = all_rows(c,"SELECT s.schedule_id,s.schedule_date,t.start_time FROM schedule s JOIN service_slot t ON s.slot_id=t.slot_id WHERE s.student_id=%s AND s.status='ACTIVE'",(student_id,))
        ids = [r['schedule_id'] for r in rows if instant(r['schedule_date'],r['start_time'])>self.clock()]
        for sid in ids:
            c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason=%s WHERE schedule_id=%s",(reason,sid))
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(sid,))
            c.execute("UPDATE transfer_application SET final_status='CANCELLED' WHERE old_schedule_id=%s AND final_status='PENDING' AND first_status<>'REJECTED'",(sid,))
        self.snapshot_memberships(c)
        return ids

    def approve_withdrawal(self, actor, withdrawal_id, approved):
        desired = 'APPROVED' if approved else 'REJECTED'
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('SUPER',))
            app = one(c,'SELECT * FROM withdrawal_application WHERE withdrawal_id=%s FOR UPDATE',(withdrawal_id,))
            require(app,'退队申请不存在',404)
            if app['approve_status']==desired:
                return {'status':desired,'replayed':True}
            require(app['approve_status']=='PENDING','申请已处理')
            self.guard_withdrawal_final(c,withdrawal_id)
            cancelled=[]
            if approved:
                self.snapshot_memberships(c)
                c.execute("UPDATE student SET status='QUIT' WHERE student_id=%s",(app['student_id'],))
                cancelled=self.cancel_future(c,app['student_id'])
            c.execute('UPDATE withdrawal_application SET approve_status=%s,admin_id=%s,approve_time=%s WHERE withdrawal_id=%s',
                      (desired,a['_id'],self.clock(),withdrawal_id))
            self.audit(c,a['_id'],'APPROVE_WITHDRAWAL','withdrawal_application',withdrawal_id,app,{'status':desired,'cancelled_schedules':cancelled})
            return {'status':desired,'cancelled_schedules':cancelled}

    def record_attendance(self, actor, schedule_id, status, remark=''):
        require(status in ('NORMAL','LATE','ABSENT','LEAVE'),'考勤状态无效',422)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('NORMAL','SUPER','LEAD'))
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
            c.execute("UPDATE transfer_application SET final_status='CANCELLED' WHERE old_schedule_id=%s AND final_status='PENDING' AND first_status<>'REJECTED'",(schedule_id,))
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
            self.actor(c,actor,('SUPER','NORMAL'))
            return all_rows(c,'SELECT * FROM service_slot ORDER BY slot_id')

    def _legacy_list_schedules(self, actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor)
            sql='''SELECT s.*,st.name AS student_name,t.team_name,t.period_no,t.start_time,t.end_time,t.location,
                t.manager_admin_id,at.attendance_status,at.source AS attendance_source,at.revision AS attendance_revision,
                EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') AS leave_approved
                FROM schedule s JOIN service_slot t ON s.slot_id=t.slot_id
                JOIN student st ON st.student_id=s.student_id
                LEFT JOIN attendance at ON at.schedule_id=s.schedule_id'''
            args=()
            if a['_role']=='STUDENT':
                sql+=' WHERE s.student_id=%s'; args=(a['_id'],)
            elif a['_role']=='NORMAL':
                sql+=' WHERE t.manager_admin_id=%s'; args=(a['_id'],)
            return all_rows(c,sql+' ORDER BY s.schedule_date,s.schedule_id',args)

    def _legacy_hours(self, actor, student_id=None, start=None, end=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT','SUPER'))
            sid=student_id or (a['_id'] if a['_role']=='STUDENT' else None)
            require(sid,'请指定学生学号',422)
            require(a['_role']=='SUPER' or sid==a['_id'],'只能查看本人时长',403)
            require(one(c,'SELECT student_id FROM student WHERE student_id=%s',(sid,)),'学生不存在',404)
            sql='''SELECT r.record_id,r.service_minutes,r.record_status,s.schedule_id,
                s.schedule_date,s.slot_id,a.attendance_status FROM service_record r
                JOIN attendance a ON a.attendance_id=r.attendance_id
                JOIN schedule s ON s.schedule_id=a.schedule_id WHERE s.student_id=%s'''
            args=[sid]
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
              'transfer':('transfer_application','transfer_id','old_schedule_id'),
              'withdrawal':('withdrawal_application','withdrawal_id',None)}
        require(kind in spec,'申请类型无效',422)
        table,key,schedule_key=spec[kind]
        with self.db.transaction() as c:
            a=self.actor(c,actor)
            sql=f'SELECT p.* FROM {table} p'; args=()
            if a['_role']=='STUDENT':
                sql+=' WHERE p.student_id=%s'; args=(a['_id'],)
            elif a['_role']=='NORMAL':
                require(schedule_key,'普通管理员不能查看退队申请',403)
                from .fixed_slots import installed
                if kind=='transfer' and installed(c):
                    sql+=' LEFT JOIN schedule s ON p.old_schedule_id=s.schedule_id JOIN service_slot t ON t.slot_id=COALESCE(p.old_slot_id,s.slot_id) WHERE t.manager_admin_id=%s'
                else:
                    sql+=f' JOIN schedule s ON p.{schedule_key}=s.schedule_id JOIN service_slot t ON s.slot_id=t.slot_id WHERE t.manager_admin_id=%s'
                args=(a['_id'],)
            rows=all_rows(c,sql+f' ORDER BY p.{key} DESC',args)
            if kind=='withdrawal':
                from .leaders import installed as leaders_installed
                if leaders_installed(c):
                    for row in rows:
                        first=one(c,'''SELECT w.status,w.reason,g.admin_id,ad.status AS admin_status,st.status AS student_status
                            FROM withdrawal_leader_review w LEFT JOIN leader_scope g ON g.scope_id=w.scope_id
                            LEFT JOIN admin ad ON ad.admin_id=g.admin_id LEFT JOIN student st ON st.student_id=ad.leader_student_id
                            WHERE w.withdrawal_id=%s''',(row['withdrawal_id'],))
                        row['first_status']=first['status'] if first else 'NOT_REQUIRED'
                        row['first_reason']=first['reason'] if first else ''
                        row['requires_first']=bool(first and first['admin_id'] and first['admin_status']=='ACTIVE' and first['student_status']=='ACTIVE' and first['status']=='PENDING')
            if kind=='transfer':
                for row in rows:
                    for prefix in ('old','new'):
                        slot_id=row.get(prefix+'_slot_id')
                        if slot_id:
                            slot=one(c,'SELECT team_name FROM service_slot WHERE slot_id=%s',(slot_id,))
                            row[prefix+'_slot_name']=slot['team_name'] if slot else None
            return rows

    def credit(self, actor, student_id=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT','SUPER'))
            sid=student_id or (a['_id'] if a['_role']=='STUDENT' else None)
            require(sid,'请指定学生',422)
            require(a['_role']=='SUPER' or sid==a['_id'],'只能查看本人信用',403)
            student=one(c,'SELECT student_id,credit_score,credit_version,status FROM student WHERE student_id=%s',(sid,))
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
                sql+=" AND EXISTS(SELECT 1 FROM slot_member m JOIN service_slot t ON m.slot_id=t.slot_id WHERE m.student_id=st.student_id AND t.manager_admin_id=%s)"
                args.append(a['_id'])
            if student_id:
                sql+=' AND st.student_id=%s';args.append(student_id)
            rows=list(all_rows(c,sql+' ORDER BY st.student_id',args))
            for row in rows:
                row['slots']=[]
            if fixed and rows:
                links=all_rows(c,'''SELECT m.student_id,m.slot_id,t.team_name,t.manager_admin_id FROM slot_member m
                    JOIN service_slot t ON t.slot_id=m.slot_id''')
                by_id={r['student_id']:r for r in rows}
                for link in links:
                    if link['student_id'] in by_id and (a['_role']=='SUPER' or link['manager_admin_id']==a['_id']):
                        by_id[link['student_id']]['slots'].append({'slot_id':link['slot_id'],'name':link['team_name']})
            return rows

    def configure_slot(self, actor, slot_id, manager_admin_id, need_num):
        require(need_num is None or isinstance(need_num,int) and 1<=need_num<=10000,'人数上限必须为 1 至 10000，或留空待设置',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','LEAD'))
            before=self.slot(c,slot_id)
            if a['_role']=='LEAD':
                self.scope(a,before)
                if manager_admin_id is not None:
                    ids=a['_lead_slots'];marks=','.join(['%s']*len(ids))
                    require(one(c,f'''SELECT 1 FROM admin ad WHERE ad.admin_id=%s AND
                        (EXISTS(SELECT 1 FROM service_slot t WHERE t.manager_admin_id=ad.admin_id AND t.slot_id IN ({marks}))
                        OR EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=ad.student_id AND m.slot_id IN ({marks})))''',[manager_admin_id]+ids*2),
                        '请选择本范围时段管理员，或先将本范围队员设为管理员',403)
            require(before.get('weekday') is not None or before.get('schedule_kind')=='WEEKLY','只能设置固定时段或按周岗位',422)
            require(before.get('business_code') not in ('GARDEN','PUBLICITY') or manager_admin_id==before['manager_admin_id'],
                    '请在业务管理中统一设置该业务的负责人',422)
            if manager_admin_id is not None:
                require(one(c,"SELECT admin_id FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",(manager_admin_id,)), '负责人须为有效普通管理员',422)
            occupied=one(c,"SELECT MAX(n) AS n FROM (SELECT COUNT(*) AS n FROM schedule WHERE slot_id=%s AND status='ACTIVE' AND schedule_date>=CURDATE() GROUP BY schedule_date) q",(slot_id,))['n'] or 0
            require(need_num is None or need_num>=occupied,'人数上限不能少于已有未来排班人数')
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
                AND p.first_status<>'REJECTED' AND NOT EXISTS
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

    def fixed_transfer_check(self, c, student_id, old_slot_id, new_slot_id, final=False):
        student=one(c,'SELECT status FROM student WHERE student_id=%s',(student_id,))
        require(student and student['status']=='ACTIVE','队员已停用或已退队')
        require(one(c,'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id=%s',
                    (student_id,old_slot_id)),'原固定班次已不属于该队员，请刷新后重新申请')
        old=self.slot(c,old_slot_id)
        target=self.slot(c,new_slot_id)
        if target.get('business_id') is not None:self._active_business(c,target['business_id'])
        require((old.get('weekday') is not None or old.get('schedule_kind')=='WEEKLY') and old['status']=='ACTIVE','原固定班次已停用')
        require((target.get('weekday') is not None or target.get('schedule_kind')=='WEEKLY') and target['status']=='ACTIVE','请选择有效的固定班次',422)
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
        if final:
            require(target['need_num'] is not None or target.get('schedule_kind')=='WEEKLY','目标时段尚未设置人数上限，请先完成时段设置')
            require(one(c,"SELECT 1 FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",
                        (target['manager_admin_id'],)),'目标时段尚未分配有效管理员，请先完成时段设置')
        if target['need_num'] is not None:
            count=one(c,'''SELECT COUNT(*) n FROM slot_member m JOIN student st ON st.student_id=m.student_id
                WHERE m.slot_id=%s AND st.status='ACTIVE' ''',(new_slot_id,))['n']
            require(count<target['need_num'],'目标固定班次人数已满')
        return old

    def apply_fixed_transfer(self, actor, old_slot_id, new_slot_id, reason):
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('STUDENT',),True)
            self.fixed_transfer_check(c,a['_id'],old_slot_id,new_slot_id)
            require(not one(c,"""SELECT 1 FROM transfer_application WHERE student_id=%s
                AND old_slot_id=%s AND first_status<>'REJECTED' AND final_status='PENDING'""",
                (a['_id'],old_slot_id)),'该固定班次已有待处理的换班申请')
            c.execute('''INSERT INTO transfer_application(student_id,old_slot_id,new_slot_id,reason)
                VALUES(%s,%s,%s,%s)''',(a['_id'],old_slot_id,new_slot_id,reason))
            tid=c.lastrowid
            self.notify_application(c,'transfer_application',tid)
            return {'transfer_id':tid}

    def approve_fixed_transfer(self, c, actor, app, stage, desired):
        old=self.slot(c,app['old_slot_id'])
        if stage=='first':
            self.scope(actor,old,True)
        if app[stage+'_status']==desired:
            return {'status':desired,'replayed':True}
        require(app[stage+'_status']=='PENDING' and app['final_status']=='PENDING','申请已处理或已取消')
        if stage=='final':
            require(app['first_status']=='APPROVED','必须先通过普通管理员初审')
        if desired=='APPROVED':
            self.fixed_transfer_check(c,app['student_id'],app['old_slot_id'],app['new_slot_id'],stage=='final')
            if stage=='final':
                self.snapshot_memberships(c)
                c.execute('DELETE FROM slot_member WHERE student_id=%s AND slot_id=%s',(app['student_id'],app['old_slot_id']))
                c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(app['student_id'],app['new_slot_id']))
                self.sync_semesters(c, strict_student=app['student_id'])
        c.execute(f'UPDATE transfer_application SET {stage}_status=%s,{stage}_admin_id=%s,{stage}_time=%s WHERE transfer_id=%s',
                  (desired,actor['_id'],self.clock(),app['transfer_id']))
        self.audit(c,actor['_id'],'TRANSFER_'+stage.upper(),'transfer_application',app['transfer_id'],app,
                   {'status':desired,'old_slot_id':app['old_slot_id'],'new_slot_id':app['new_slot_id']},'每周固定班次调整')
        return {'status':desired,'fixed_membership_updated':stage=='final' and desired=='APPROVED'}

    def import_roster(self, actor, file_base64, sheet_name=None, map_categories=True,
                      commit=False, initial_password=None, accept_warnings=False,business_id=None):
        from .roster import parse_workbook
        with self.db.transaction() as c:
            self.actor(c,actor,('SUPER',))
        try:
            preview=parse_workbook(file_base64,sheet_name,map_categories)
        except Exception as exc:
            if isinstance(exc,ValueError):
                raise DomainError(str(exc),422) from exc
            raise DomainError('无法读取该工作簿，请检查是否为有效的 .xlsx 文件',422) from exc
        # Reparse and revalidate the submitted workbook on every commit.
        with self.db.transaction(commit) as c:
            a=self.actor(c,actor,('SUPER',))
            from .business_schema import installed as business_installed
            multi=business_installed(c)
            if multi:
                biz=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,)) if business_id else one(c,"SELECT * FROM business WHERE code='CONSULT'")
                require(biz and biz['kind']=='FIXED','请选择咨询服务、美育或青广宣传；专项时长使用专项导入',422)
                slots=all_rows(c,'SELECT slot_id,weekday,period_no FROM service_slot WHERE business_id=%s AND weekday IS NOT NULL',(biz['business_id'],))
                preview['business_name']=biz['name']
            else:slots=all_rows(c,'SELECT slot_id,weekday,period_no FROM service_slot WHERE weekday IS NOT NULL')
            mapping={(s['weekday'],s['period_no']):s['slot_id'] for s in slots}
            existing={r['student_id']:r for r in all_rows(c,'SELECT student_id,name,status FROM student')}
            for person in preview['students']:
                old=existing.get(person['student_id'])
                person['action']='existing' if old else 'new'
                if old and (old['name']!=person['name'] or old['status']!='ACTIVE'):
                    preview['errors'].append({'row':person['rows'][0],'message':f'学号 {person["student_id"]} 已存在但姓名不同或账号不在队，不会覆盖或重新启用'})
                try:
                    require(all(tuple(pair) in mapping for pair in person['slots']),'所选业务没有表格中的时段，请核对业务与时段编号',422)
                    if multi:
                        previous=[r['slot_id'] for r in all_rows(c,'SELECT slot_id FROM slot_member WHERE student_id=%s',(person['student_id'],))]
                        self._validate_memberships(c,person['student_id'],previous+[mapping[tuple(pair)] for pair in person['slots']])
                except DomainError as exc:
                    preview['errors'].append({'row':person['rows'][0],'message':exc.message})
            preview['new_students']=sum(p['action']=='new' for p in preview['students'])
            preview['existing_students']=len(preview['students'])-preview['new_students']
            if not commit:
                return preview
            require(not preview['errors'],'预览存在错误，请先修正工作簿后重试',422)
            require(not preview['warnings'] or accept_warnings,'请先确认导入预览中的提示',422)
            require(preview['students'],'没有可导入的队员',422)
            require(initial_password and 8<=len(initial_password)<=128,'请设置 8 至 128 字符的新队员初始密码',422)
            require(mapping,'固定时段尚未初始化')
            added_memberships=0
            self.snapshot_memberships(c)
            for person in preview['students']:
                sid=person['student_id']
                if person['action']=='new':
                    c.execute('INSERT INTO student(student_id,name,college,password_hash) VALUES(%s,%s,%s,%s)',
                              (sid,person['name'],person['college'],hash_password(initial_password)))
                for pair in person['slots']:
                    slot_id=mapping[tuple(pair)]
                    if not one(c,'SELECT student_id FROM slot_member WHERE student_id=%s AND slot_id=%s',(sid,slot_id)):
                        c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(sid,slot_id));added_memberships+=1
            summary={'new_students':preview['new_students'],'existing_students':preview['existing_students'],'added_memberships':added_memberships}
            self.audit(c,a['_id'],'IMPORT_ROSTER','student','batch',after=summary,reason='Excel 队员导入')
            self.sync_semesters(c)
            return summary
