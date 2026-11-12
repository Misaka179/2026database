"""Transactional, recipient-scoped in-app notifications."""
from .db import one,all_rows
from .collection_governance_schema import installed


class InboxService:
    def _super_recipients(self,c):
        return [('admin',r['admin_id']) for r in all_rows(c,"SELECT admin_id FROM admin WHERE role='SUPER' AND status='ACTIVE'")]

    def _active_admin(self,c,admin_id):
        if admin_id is None:return []
        row=one(c,"SELECT admin_id FROM admin WHERE admin_id=%s AND status='ACTIVE'",(admin_id,))
        return [('admin',row['admin_id'])] if row else []

    def _slot_reviewer_recipients(self,c,slot_id):
        """All ordinary administrators who may review an application on this slot.

        The reviewer pool is the slot manager, the business owner and the active
        leader scope for that business/weekday.  Super administrators are not in
        this pool; they only take over when the pool is empty and receive the
        decision as a read-only copy otherwise.
        """
        if slot_id is None:return []
        slot=one(c,'SELECT * FROM service_slot WHERE slot_id=%s',(slot_id,))
        if not slot:return []
        recipients=[]
        recipients.extend(self._active_admin(c,slot.get('manager_admin_id')))
        if slot.get('business_id') is not None:
            from .service import business_owner_available
            if business_owner_available(c):
                owner=one(c,'SELECT total_manager_admin_id FROM business WHERE business_id=%s',(slot['business_id'],))
                if owner:recipients.extend(self._active_admin(c,owner['total_manager_admin_id']))
            from .leaders import installed as leaders_installed
            if leaders_installed(c) and slot.get('weekday') is not None:
                for row in all_rows(c,'''SELECT g.admin_id FROM leader_scope g JOIN admin ad ON ad.admin_id=g.admin_id
                    WHERE g.business_id=%s AND g.weekday=%s AND g.active=1 AND ad.status='ACTIVE' ''',
                    (slot['business_id'],slot['weekday'])):
                    recipients.append(('admin',row['admin_id']))
        return list(dict.fromkeys(recipients))

    def _withdrawal_reviewer_recipients(self,c,withdrawal_id):
        row=one(c,'''SELECT g.admin_id FROM withdrawal_leader_review w
            JOIN leader_scope g ON g.scope_id=w.scope_id
            JOIN admin ad ON ad.admin_id=g.admin_id
            WHERE w.withdrawal_id=%s AND w.scope_id IS NOT NULL AND g.active=1 AND ad.status='ACTIVE' ''',
            (withdrawal_id,))
        return [('admin',row['admin_id'])] if row else []

    def _withdrawal_reviewer_admin(self,c,withdrawal_id):
        row=self._withdrawal_reviewer_recipients(c,withdrawal_id)
        return row[0][1] if row else None

    def _can_review_withdrawal(self,c,a,student_id):
        """退队申请：时段负责人、业务总负责人、分队负责人或超管均可一次审核。"""
        if a['_role']=='SUPER':return True
        if a['_role']!='NORMAL':return False
        if one(c,'''SELECT 1 FROM slot_member m
            JOIN service_slot t ON t.slot_id=m.slot_id
            LEFT JOIN business b ON b.business_id=t.business_id
            WHERE m.student_id=%s AND (t.manager_admin_id=%s OR b.total_manager_admin_id=%s) ''',
                (student_id,a['_id'],a['_id'])):
            return True
        if one(c,'''SELECT 1 FROM business_member bm JOIN business b ON b.business_id=bm.business_id
            WHERE bm.student_id=%s AND b.total_manager_admin_id=%s
            AND bm.effective_from<=CURDATE() AND (bm.effective_until IS NULL OR bm.effective_until>=CURDATE())''',
                (student_id,a['_id'])):
            return True
        from .leaders import installed as leaders_installed
        return bool(leaders_installed(c) and one(c,'''SELECT 1 FROM slot_member m
            JOIN service_slot t ON t.slot_id=m.slot_id
            JOIN leader_scope g ON g.business_id=t.business_id AND g.weekday=t.weekday
            WHERE m.student_id=%s AND g.admin_id=%s AND g.active=1''',
                (student_id,a['_id'])))

    def _notice(self,c,recipients,event_key,category,title,message,page,target=None):
        if not installed(c):return
        for kind,recipient in {(kind,str(recipient)) for kind,recipient in recipients if recipient is not None}:
            c.execute('''INSERT IGNORE INTO inbox_notice(recipient_kind,recipient_id,event_key,category,title,message,target_page,target_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (kind,recipient,event_key,category,title,message[:1000],page,str(target) if target is not None else None,self.clock()))

    def inbox(self,actor,unread_only=False,before_id=None,limit=50,category=None):
        from .service import require
        category=category or None
        require(type(limit)==int and 1<=limit<=100,'每页通知数量须在1至100之间',422)
        require(category in (None,'APPLICATION','SERVICE','ACCOUNT','COLLECTION','SCOPE'),'通知类型无效',422)
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'));where='recipient_kind=%s AND recipient_id=%s';args=[a['_kind'],str(a['_id'])]
            count=one(c,'SELECT COUNT(*) n FROM inbox_notice WHERE '+where+' AND read_at IS NULL',args)['n']
            if unread_only:where+=' AND read_at IS NULL'
            if category:where+=' AND category=%s';args.append(category)
            if before_id is not None:where+=' AND notice_id<%s';args.append(before_id)
            rows=list(all_rows(c,'SELECT notice_id,category,title,message,target_page,target_id,created_at,read_at FROM inbox_notice WHERE '+where+' ORDER BY notice_id DESC LIMIT %s',args+[limit+1]))
            return {'unread_count':count,'items':rows[:limit],'next_cursor':rows[limit-1]['notice_id'] if len(rows)>limit else None}

    def read_notice(self,actor,notice_id=None):
        from .service import require
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'));args=[a['_kind'],str(a['_id'])]
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
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'))
            marks=','.join(['%s']*len(ids))
            rows=all_rows(c,f'SELECT notice_id,read_at FROM inbox_notice WHERE recipient_kind=%s AND recipient_id=%s AND notice_id IN ({marks}) FOR UPDATE',[a['_kind'],str(a['_id'])]+ids)
            require(len(rows)==len(ids),'所选通知不存在或不属于当前账号，整批未修改',404)
            c.execute(f'UPDATE inbox_notice SET read_at=COALESCE(read_at,%s) WHERE notice_id IN ({marks})',[self.clock()]+ids)
            return {'status':'READ','updated':sum(r['read_at'] is None for r in rows),'selected':len(ids)}

    def notify_application(self,c,table,application_id):
        if not installed(c):return
        spec={'leave_application':('leave_id','请假'),'transfer_application':('transfer_id','长期换班'),'withdrawal_application':('withdrawal_id','退队')}
        key,title=spec[table];page='applications:'+{'leave_application':'leave','transfer_application':'transfer','withdrawal_application':'withdrawal'}[table];r=one(c,f'SELECT * FROM {table} WHERE {key}=%s',(application_id,))
        if table=='withdrawal_application':
            recipients=self._withdrawal_reviewer_recipients(c,application_id)
            if not recipients:recipients=self._super_recipients(c)
        else:
            if table=='leave_application':
                row=one(c,'SELECT s.slot_id FROM schedule s WHERE s.schedule_id=%s',(r['schedule_id'],))
                slot_id=row['slot_id'] if row else None
            else:
                slot_id=r.get('old_slot_id')
            recipients=self._slot_reviewer_recipients(c,slot_id)
            if not recipients:recipients=self._super_recipients(c)
        student=one(c,'SELECT name FROM student WHERE student_id=%s',(r['student_id'],))
        who=f"{student['name']}（{r['student_id']}）" if student and student['name'] else f"学号 {r['student_id']}"
        self._notice(c,recipients,f'application:{table}:{application_id}','APPLICATION',title+'待审批',f'{who}提交申请。',page,application_id)
        self._notice(c,[('student',r['student_id'])],f'application-received:{table}:{application_id}','APPLICATION',title+'已提交','等待审批结果。',page,application_id)

    def notify_result_copy(self,c,table,application_id,title,status,reviewer_id,reason=''):
        """Send the final decision to super administrators as a read-only copy."""
        if not installed(c) or status not in ('APPROVED','REJECTED'):return
        recipients=[(kind,recipient) for kind,recipient in self._super_recipients(c)
                    if reviewer_id is None or str(recipient)!=str(reviewer_id)]
        if not recipients:return
        pages={'leave_application':'leave','transfer_application':'transfer','withdrawal_application':'withdrawal'}
        keys={'leave_application':'leave_id','transfer_application':'transfer_id','withdrawal_application':'withdrawal_id'}
        page='applications:'+pages[table]
        student=one(c,f'SELECT student_id FROM {table} WHERE {keys[table]}=%s',(application_id,))
        reviewer=one(c,'SELECT name FROM admin WHERE admin_id=%s',(reviewer_id,)) if reviewer_id else None
        result={'APPROVED':'通过','REJECTED':'驳回'}.get(status,status)
        reason=(reason or '').strip()
        sid=student['student_id'] if student else ''
        name=one(c,'SELECT name FROM student WHERE student_id=%s',(sid,)) if sid else None
        who=f"{name['name']}（{sid}）" if name and name['name'] else f"学号 {sid}"
        message=f'{who} · {result}'+(f' · 审核人 {reviewer["name"]}' if reviewer else '')+(f'；原因：{reason}' if reason else '')
        self._notice(c,recipients,f'application-result:{table}:{application_id}','APPLICATION',
                     title+'审核结果',message,page,application_id)

    def notify_audit(self,c,log_id,operation,table,target,before,after,reason,operator_id=None):
        if not installed(c):return
        after=after or {};before=before or {};key=f'audit:{log_id}'
        labels={'APPROVED':'通过','REJECTED':'打回','CANCELLED':'取消','PENDING':'待处理'}
        if operation in ('APPROVE_LEAVE','APPROVE_WITHDRAWAL','TRANSFER_REVIEW','TRANSFER_FIRST','TRANSFER_FINAL'):
            title={'APPROVE_LEAVE':'请假','APPROVE_WITHDRAWAL':'退队','TRANSFER_REVIEW':'长期换班',
                   'TRANSFER_FIRST':'长期换班（历史初审）','TRANSFER_FINAL':'长期换班（历史终审）'}[operation]
            sid=before.get('student_id');status=after.get('status','');page='applications:'+('leave' if operation=='APPROVE_LEAVE' else 'withdrawal' if operation=='APPROVE_WITHDRAWAL' else 'transfer')
            reason_text=(reason or '').strip()
            self._notice(c,[('student',sid)],key,'APPLICATION',title+'结果：'+labels.get(status,status),reason_text if reason_text and not reason_text.isdigit() else '',page,target)
            if operation=='TRANSFER_FIRST' and status=='APPROVED':
                self._notice(c,self._super_recipients(c),key,'APPLICATION','长期换班待终审',f'学号 {sid} 已通过初审。',page,target)
            elif operation in ('APPROVE_LEAVE','APPROVE_WITHDRAWAL','TRANSFER_REVIEW'):
                self.notify_result_copy(c,table,target,title,status,operator_id,reason)
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
            reason_text=(reason or '').strip()
            message=reason_text if reason_text and not reason_text.isdigit() else ''
            self._notice(c,[('student',sid)],key,'SERVICE',title,message,page,target)
