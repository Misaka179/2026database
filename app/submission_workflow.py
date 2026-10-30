"""Two-stage hour claims with private files and auditable final corrections."""
from .db import one,all_rows
from .collection_support import CollectionSupport,decode_attachments


class SubmissionWorkflow(CollectionSupport):
    def _submission_row(self,c,submission_id):
        return one(c,'''SELECT s.*,i.title,h.business_id,h.collection_id,h.title AS collection_title,h.group_id,h.minute_step
            FROM hour_submission s JOIN collection_item i ON i.item_id=s.item_id
            JOIN hour_collection h ON h.collection_id=i.collection_id WHERE s.submission_id=%s FOR UPDATE''',(submission_id,))

    def _submission_read_scope(self,c,a,row):
        from .service import require
        if a['_role']=='STUDENT':require(str(row['student_id'])==str(a['_id']),'只能查看本人的申报附件',403)
        else:self._collection_scope(c,a,row['business_id'],row.get('group_id'))

    def submission_attachment(self,actor,submission_id,attachment_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'));row=self._submission_row(c,submission_id)
            require(row,'申报不存在',404);self._submission_read_scope(c,a,row)
            f=one(c,'SELECT * FROM submission_attachment WHERE submission_id=%s AND attachment_id=%s',(submission_id,attachment_id))
            require(f,'附件不存在',404);return f

    def submit_hours(self,actor,item_id,service_date,service_minutes,remark='',expected_revision=None,attachments=None):
        from .service import require,parse_date
        with self.db.transaction() as c:self.actor(c,actor,('STUDENT',),True)
        files=decode_attachments(attachments) if attachments is not None else None
        day=parse_date(service_date)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('STUDENT',),True)
            item=one(c,'''SELECT i.*,h.start_date,h.end_date,h.submission_deadline,h.status AS collection_status,h.business_id,
                h.title AS collection_title,h.group_id,h.minute_step FROM collection_item i JOIN hour_collection h ON h.collection_id=i.collection_id WHERE item_id=%s''',(item_id,))
            require(item,'工作事项不存在',404)
            from .hour_units import validate_half_hour
            validate_half_hour(service_minutes)
            require(one(c,'SELECT 1 FROM collection_person WHERE collection_id=%s AND student_id=%s',(item['collection_id'],a['_id'])),'不在本次征集范围',403)
            require(item['collection_status']=='OPEN' and (not item['submission_deadline'] or self.clock().date()<=item['submission_deadline']),'征集已结束或超过申报截止日期，不能提交或重报',422)
            require(item['start_date']<=day<=item['end_date'] and day<=self.clock().date(),'服务日期须在征集范围内且不能为未来日期',422)
            require(type(service_minutes)==int and item['min_minutes']<=service_minutes<=item['max_minutes'],'时长不在该工作每天允许的分钟范围内',422)
            old=one(c,'SELECT * FROM hour_submission WHERE item_id=%s AND student_id=%s AND service_date=%s FOR UPDATE',(item_id,a['_id'],day))
            if old:
                old_files=all_rows(c,'SELECT filename,mime_type,size_bytes,content FROM submission_attachment WHERE submission_id=%s AND submission_revision=%s ORDER BY attachment_id',(old['submission_id'],old['attachment_revision']))
                same_files=files is None or files==list(old_files)
                if old['status']=='PENDING' and old['service_minutes']==service_minutes and old['remark']==remark and same_files:return {'submission_id':old['submission_id'],'replayed':True}
                require(old['status']=='REJECTED' and expected_revision==old['revision'],'该日期事项已申报；仅打回后可按最新版本重报',409)
                sid=old['submission_id'];revision=old['revision']+1
                c.execute("UPDATE hour_submission SET service_minutes=%s,remark=%s,status='PENDING',rejection_reason='',revision=%s,first_admin_id=NULL,final_admin_id=NULL WHERE submission_id=%s",(service_minutes,remark,revision,sid))
            else:
                c.execute('INSERT INTO hour_submission(item_id,student_id,service_date,service_minutes,remark) VALUES(%s,%s,%s,%s,%s)',(item_id,a['_id'],day,service_minutes,remark))
                sid=c.lastrowid;revision=1
            if files is not None:
                c.execute('UPDATE hour_submission SET attachment_revision=%s WHERE submission_id=%s',(revision,sid))
                for f in files:c.execute('INSERT INTO submission_attachment(submission_id,submission_revision,filename,mime_type,size_bytes,content) VALUES(%s,%s,%s,%s,%s,%s)',(sid,revision,f['filename'],f['mime_type'],f['size_bytes'],f['content']))
            managers=self._collection_admins(c,item['business_id'],item.get('group_id'))
            recipients=[('admin',m['admin_id']) for m in managers] or self._super_recipients(c)
            self._notice(c,recipients,f'claim-submitted:{sid}:{revision}','CLAIM','时长申报待'+('初审' if managers else '终审'),f"{a['name']} 提交了 {item['collection_title']} 的时长申报。",'collections',item['collection_id'])
            return {'submission_id':sid}

    def _claim_ledger(self,c,row,approved,minutes,admin_id):
        schedule_id=row['schedule_id']
        if not approved:
            if schedule_id:
                c.execute("UPDATE service_record r JOIN attendance a ON a.attendance_id=r.attendance_id SET r.record_status='VOID' WHERE a.schedule_id=%s",(schedule_id,))
                c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='CLAIM_REJECTED' WHERE schedule_id=%s",(schedule_id,))
            return schedule_id
        if schedule_id:
            current=one(c,'SELECT * FROM schedule WHERE schedule_id=%s',(schedule_id,))
            occupied=one(c,"SELECT 1 FROM schedule WHERE student_id=%s AND slot_id=%s AND schedule_date=%s AND status IN ('ACTIVE','COMPLETED') AND schedule_id<>%s",
                         (current['student_id'],current['slot_id'],current['schedule_date'],schedule_id))
            if occupied:
                c.execute('''INSERT INTO service_slot(business_id,schedule_kind,team_name,period_no,start_time,end_time,location,service_minutes,manager_admin_id)
                    SELECT business_id,schedule_kind,team_name,period_no,start_time,end_time,location,service_minutes,manager_admin_id
                    FROM service_slot WHERE slot_id=%s''',(current['slot_id'],))
                replacement=c.lastrowid
                c.execute('UPDATE schedule SET slot_id=%s WHERE schedule_id=%s',(replacement,schedule_id))
            c.execute("UPDATE schedule SET status='COMPLETED',cancel_reason=NULL,recognition_minutes=%s WHERE schedule_id=%s",(minutes,schedule_id))
            c.execute("UPDATE service_record r JOIN attendance a ON a.attendance_id=r.attendance_id SET r.service_minutes=%s,r.record_status='VALID' WHERE a.schedule_id=%s",(minutes,schedule_id))
            return schedule_id
        sid=self._event_record(c,row['student_id'],row['business_id'],row['title'],row['service_date'],minutes,admin_id,'CLAIM_APPROVED',f"claim:{row['submission_id']}")
        c.execute('UPDATE schedule SET group_id=%s WHERE schedule_id=%s',(row.get('group_id'),sid))
        return sid

    def decide_hours(self,actor,submission_id,approved,expected_revision,reason=''):
        from .service import require,reason_text
        if not approved:reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            return self._decide_hours(c,a,submission_id,approved,expected_revision,reason)

    def _decide_hours(self,c,a,submission_id,approved,expected_revision,reason):
        from .service import require
        row=self._submission_row(c,submission_id)
        require(row,'申报不存在',404);self._collection_scope(c,a,row['business_id'],row.get('group_id'))
        stage='FIRST' if a['_role']=='NORMAL' else 'FINAL'
        desired=('FIRST_APPROVED' if stage=='FIRST' else 'APPROVED') if approved else 'REJECTED'
        previous=one(c,'SELECT * FROM submission_review WHERE submission_id=%s AND revision=%s',(submission_id,expected_revision+1))
        if row['revision']==expected_revision+1 and previous and previous['stage']==stage and previous['admin_id']==a['_id'] and bool(previous['approved'])==approved:return {'replayed':True,'status':row['status']}
        require(row['revision']==expected_revision,'申报版本已变化，请刷新',409)
        allowed=row['status']=='PENDING' if stage=='FIRST' else row['status']=='FIRST_APPROVED' or row['status']=='PENDING' and not self._collection_admins(c,row['business_id'],row.get('group_id'))
        require(allowed,'该申报尚未完成初审或已经处理，请刷新',409)
        schedule_id=row['schedule_id']
        if stage=='FINAL':schedule_id=self._claim_ledger(c,row,approved,row['service_minutes'],a['_id'])
        column='first_admin_id' if stage=='FIRST' else 'final_admin_id'
        c.execute(f'UPDATE hour_submission SET status=%s,rejection_reason=%s,revision=revision+1,schedule_id=%s,{column}=%s WHERE submission_id=%s',(desired,reason,schedule_id,a['_id'],submission_id))
        c.execute('INSERT INTO submission_review(submission_id,revision,stage,admin_id,approved,service_minutes,reason,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(submission_id,expected_revision+1,stage,a['_id'],approved,row['service_minutes'],reason,self.clock()))
        self.audit(c,a['_id'],'REVIEW_HOURS_'+stage,'hour_submission',submission_id,row,{'status':desired,'schedule_id':schedule_id},reason)
        self._notice(c,[('student',row['student_id'])],f'claim-reviewed:{submission_id}:{expected_revision+1}','CLAIM','时长申报'+('初审' if stage=='FIRST' else '终审')+('通过' if approved else '打回'),reason or ('初审通过，等待超级管理员终审后计时。' if stage=='FIRST' else '终审通过，已计入服务时长。'),'collections',row['collection_id'])
        if stage=='FIRST':self._notice(c,self._super_recipients(c),f'claim-report:{submission_id}:{expected_revision+1}','CLAIM','时长初审结果已报送',f"{row['collection_title']}：学号 {row['student_id']} 的申报"+('待终审。' if approved else '初审被打回，可查看或二次更正。'),'collections',row['collection_id'])
        else:self._notice(c,[('admin',row['first_admin_id'])],f'claim-final:{submission_id}:{expected_revision+1}','CLAIM','时长终审结果',reason or ('终审通过，时长已入账。' if approved else '终审打回。'),'collections',row['collection_id'])
        return {'status':desired,'schedule_id':schedule_id}

    def approve_hours_batch(self,actor,collection_id,items,reason=''):
        from .service import require,DomainError
        require(items and len({i['submission_id'] for i in items})==len(items),'请选择不重复的申报条目',422)
        require(isinstance(reason,str) and len(reason)<=500,'审批说明最多500字',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            require(one(c,'SELECT 1 FROM hour_collection WHERE collection_id=%s',(collection_id,)),'征集不存在',404)
            errors=[];approved=0;replayed=0
            for item in sorted(items,key=lambda i:i['submission_id']):
                sid=item['submission_id']
                try:
                    row=self._submission_row(c,sid)
                    require(row and row['collection_id']==collection_id,'条目不存在或不属于本次征集',409)
                    result=self._decide_hours(c,a,sid,True,item['expected_revision'],reason)
                    if result.get('replayed'):replayed+=1
                    else:approved+=1
                except DomainError as exc:errors.append(f'#{sid}：{exc.message}')
            require(not errors,'整批未提交，请核对并刷新以下条目：'+'；'.join(errors),409)
            return {'approved':approved,'replayed':replayed}

    def correct_hours_review(self,actor,submission_id,approved,expected_revision,reason,service_minutes=None):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));row=self._submission_row(c,submission_id)
            require(row,'申报不存在',404)
            minutes=row['service_minutes'] if service_minutes is None else service_minutes
            if row['minute_step']==30:
                from .hour_units import validate_half_hour
                validate_half_hour(minutes)
            require(type(minutes)==int and 0<=minutes<=1440,'更正分钟数须为0至1440的整数',422)
            previous=one(c,'SELECT * FROM submission_review WHERE submission_id=%s AND revision=%s',(submission_id,expected_revision+1))
            if row['revision']==expected_revision+1 and previous and previous['stage']=='CORRECTION' and previous['admin_id']==a['_id'] and bool(previous['approved'])==approved and previous['service_minutes']==minutes and previous['reason']==reason:return {'replayed':True,'status':row['status']}
            require(row['revision']==expected_revision and row['status'] in ('APPROVED','REJECTED'),'只能更正已通过或已打回的最新审批结果',409)
            desired='APPROVED' if approved else 'REJECTED';schedule_id=self._claim_ledger(c,row,approved,minutes,a['_id'])
            c.execute('UPDATE hour_submission SET status=%s,service_minutes=%s,rejection_reason=%s,revision=revision+1,schedule_id=%s,final_admin_id=%s WHERE submission_id=%s',(desired,minutes,reason,schedule_id,a['_id'],submission_id))
            c.execute('INSERT INTO submission_review(submission_id,revision,stage,admin_id,approved,service_minutes,reason,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(submission_id,expected_revision+1,'CORRECTION',a['_id'],approved,minutes,reason,self.clock()))
            self.audit(c,a['_id'],'CORRECT_HOURS_REVIEW','hour_submission',submission_id,row,{'status':desired,'service_minutes':minutes,'schedule_id':schedule_id},reason)
            recipients=[('student',row['student_id'])]+[('admin',m['admin_id']) for m in self._collection_admins(c,row['business_id'],row.get('group_id'))]
            self._notice(c,recipients,f'claim-corrected:{submission_id}:{expected_revision+1}','CLAIM','时长审批结果已更正',reason,'collections',row['collection_id'])
            return {'status':desired,'schedule_id':schedule_id}
