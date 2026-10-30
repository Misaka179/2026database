"""Transactional, recipient-scoped in-app notifications."""
from .db import one,all_rows
from .collection_governance_schema import installed


class InboxService:
    def _super_recipients(self,c):
        return [('admin',r['admin_id']) for r in all_rows(c,"SELECT admin_id FROM admin WHERE role='SUPER' AND status='ACTIVE'")]

    def _notice(self,c,recipients,event_key,category,title,message,page,target=None):
        if not installed(c):return
        for kind,recipient in {(kind,str(recipient)) for kind,recipient in recipients if recipient is not None}:
            c.execute('''INSERT IGNORE INTO inbox_notice(recipient_kind,recipient_id,event_key,category,title,message,target_page,target_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (kind,recipient,event_key,category,title,message[:1000],page,str(target) if target is not None else None,self.clock()))

    def inbox(self,actor,unread_only=False,before_id=None,limit=50):
        from .service import require
        require(type(limit)==int and 1<=limit<=100,'每页通知数量须在1至100之间',422)
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT','LEAD'));where='recipient_kind=%s AND recipient_id=%s';args=[a['_kind'],str(a['_id'])]
            count=one(c,'SELECT COUNT(*) n FROM inbox_notice WHERE '+where+' AND read_at IS NULL',args)['n']
            if unread_only:where+=' AND read_at IS NULL'
            if before_id is not None:where+=' AND notice_id<%s';args.append(before_id)
            rows=list(all_rows(c,'SELECT notice_id,category,title,message,target_page,target_id,created_at,read_at FROM inbox_notice WHERE '+where+' ORDER BY notice_id DESC LIMIT %s',args+[limit+1]))
            return {'unread_count':count,'items':rows[:limit],'next_cursor':rows[limit-1]['notice_id'] if len(rows)>limit else None}

    def read_notice(self,actor,notice_id=None):
        from .service import require
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT','LEAD'));args=[a['_kind'],str(a['_id'])]
            if notice_id is not None:
                require(one(c,'SELECT 1 FROM inbox_notice WHERE recipient_kind=%s AND recipient_id=%s AND notice_id=%s',args+[notice_id]),'通知不存在',404)
            c.execute('UPDATE inbox_notice SET read_at=COALESCE(read_at,%s) WHERE recipient_kind=%s AND recipient_id=%s'+(' AND notice_id=%s' if notice_id is not None else ''),
                      [self.clock()]+args+([notice_id] if notice_id is not None else []))
            return {'status':'READ'}

    def read_notices_batch(self,actor,notice_ids):
        from .service import require
        require(notice_ids,'请选择通知',422)
        ids=sorted(set(notice_ids))
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT','LEAD'))
            marks=','.join(['%s']*len(ids))
            rows=all_rows(c,f'SELECT notice_id,read_at FROM inbox_notice WHERE recipient_kind=%s AND recipient_id=%s AND notice_id IN ({marks}) FOR UPDATE',[a['_kind'],str(a['_id'])]+ids)
            require(len(rows)==len(ids),'所选通知不存在或不属于当前账号，整批未修改',404)
            c.execute(f'UPDATE inbox_notice SET read_at=COALESCE(read_at,%s) WHERE notice_id IN ({marks})',[self.clock()]+ids)
            return {'status':'READ','updated':sum(r['read_at'] is None for r in rows),'selected':len(ids)}

    def notify_application(self,c,table,application_id):
        if not installed(c):return
        spec={'leave_application':('leave_id','请假'),'transfer_application':('transfer_id','长期换班'),'withdrawal_application':('withdrawal_id','退队')}
        key,title=spec[table];page='applications:'+{'leave_application':'leave','transfer_application':'transfer','withdrawal_application':'withdrawal'}[table];r=one(c,f'SELECT * FROM {table} WHERE {key}=%s',(application_id,))
        recipients=[]
        if table=='withdrawal_application':
            recipients=self._super_recipients(c)
            from .leaders import installed as leaders_installed
            if leaders_installed(c):
                scope=one(c,'''SELECT g.admin_id FROM withdrawal_leader_review w JOIN leader_scope g ON g.scope_id=w.scope_id WHERE w.withdrawal_id=%s''',(application_id,))
                if scope and scope['admin_id']:recipients=[('admin',scope['admin_id'])]+recipients
        elif r.get('old_slot_id'):
            slot=one(c,'SELECT manager_admin_id FROM service_slot WHERE slot_id=%s',(r['old_slot_id'],));recipients=[('admin',slot['manager_admin_id'])]
        else:
            slot=one(c,'SELECT t.manager_admin_id FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id WHERE s.schedule_id=%s',(r.get('schedule_id') or r.get('old_schedule_id'),))
            if slot:recipients=[('admin',slot['manager_admin_id'])]
        self._notice(c,recipients,f'application:{table}:{application_id}','APPLICATION',title+'申请待审批',f"学号 {r['student_id']} 提交了{title}申请，请查看。",page,application_id)
        self._notice(c,[('student',r['student_id'])],f'application-received:{table}:{application_id}','APPLICATION',title+'申请已提交','申请已进入审批流程，可在申请记录查看进度。',page,application_id)

    def notify_audit(self,c,log_id,operation,table,target,before,after,reason):
        if not installed(c):return
        after=after or {};before=before or {};key=f'audit:{log_id}'
        labels={'APPROVED':'通过','REJECTED':'打回','CANCELLED':'取消','PENDING':'待处理'}
        if operation in ('APPROVE_LEAVE','APPROVE_WITHDRAWAL','TRANSFER_FIRST','TRANSFER_FINAL'):
            title={'APPROVE_LEAVE':'请假','APPROVE_WITHDRAWAL':'退队','TRANSFER_FIRST':'长期换班初审','TRANSFER_FINAL':'长期换班终审'}[operation]
            sid=before.get('student_id');status=after.get('status','');page='applications:'+('leave' if operation=='APPROVE_LEAVE' else 'withdrawal' if operation=='APPROVE_WITHDRAWAL' else 'transfer')
            self._notice(c,[('student',sid)],key,'APPLICATION',title+'结果：'+labels.get(status,status),reason or '请进入申请记录查看审批结果。',page,target)
            if operation=='TRANSFER_FIRST' and status=='APPROVED':
                self._notice(c,self._super_recipients(c),key,'APPLICATION','长期换班待终审',f'学号 {sid} 的申请已通过初审。',page,target)
        elif operation=='RESET_PASSWORD':
            recipients=[('student',after.get('student_id'))]
            if table=='admin':recipients.append(('admin',target))
            if after.get('student_id'):
                recipients.extend(('admin',r['admin_id']) for r in all_rows(c,'SELECT admin_id FROM admin WHERE student_id=%s',(after['student_id'],)))
            self._notice(c,recipients,key,'ACCOUNT','账号密码已重置','超级管理员已重置密码，请向管理员获取新密码。','overview',target)
        elif operation in ('REVISE_HOURS','CORRECT_ATTENDANCE','SET_STUDENT_CREDIT','CREATE_SCHEDULE','CANCEL_SCHEDULE','RECOGNIZE_EVENT','CREATE_EVENT'):
            sid=before.get('student_id') or after.get('student_id')
            if not sid and table=='student':sid=target
            if not sid and table=='schedule':
                row=one(c,'SELECT student_id FROM schedule WHERE schedule_id=%s',(target,));sid=row['student_id'] if row else None
            if not sid and table in ('attendance','service_record'):
                if table=='attendance':row=one(c,'SELECT s.student_id FROM attendance a JOIN schedule s ON s.schedule_id=a.schedule_id WHERE a.attendance_id=%s',(target,))
                else:row=one(c,'SELECT s.student_id FROM service_record r JOIN attendance a ON a.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=a.schedule_id WHERE r.record_id=%s',(target,))
                sid=row['student_id'] if row else None
            title={'REVISE_HOURS':'服务时长已修正','CORRECT_ATTENDANCE':'考勤已改判','SET_STUDENT_CREDIT':'信用分已调整','CREATE_SCHEDULE':'新增服务安排','CANCEL_SCHEDULE':'服务安排已取消','RECOGNIZE_EVENT':'临时服务时长已认定','CREATE_EVENT':'新增临时服务'}[operation]
            page='hours' if operation in ('REVISE_HOURS','RECOGNIZE_EVENT') else 'credit' if operation=='SET_STUDENT_CREDIT' else 'schedules'
            self._notice(c,[('student',sid)],key,'SERVICE',title,reason or '请查看相关记录了解详情。',page,target)
