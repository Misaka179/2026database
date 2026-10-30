"""Audited weekly stops, nonfixed claims and private leave evidence."""
import base64
import hashlib
import json
from datetime import datetime, time, timedelta
from .db import one, all_rows
from .semester import monday
from .business_schema import installed
from .collection_support import decode_attachments
from .submission_workflow import SubmissionWorkflow


class BusinessWorkflows(SubmissionWorkflow):
    def business_weeks(self,actor,semester_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            term=one(c,'SELECT * FROM semester WHERE semester_id=%s',(semester_id,))
            require(term,'学期不存在',404)
            rows=[]
            for b in all_rows(c,"SELECT * FROM business WHERE code IN ('GARDEN','PUBLICITY')"):
                if a['_role']=='NORMAL' and b['manager_admin_id']!=a['_id']: continue
                saved={r['week_no']:r for r in all_rows(c,'SELECT * FROM business_week WHERE semester_id=%s AND business_id=%s',(semester_id,b['business_id']))}
                for week in range(1,term['end_week']+1):
                    start=monday(term['start_date'])+timedelta(weeks=week-1)
                    rows.append({'business_id':b['business_id'],'business_name':b['name'],'week_no':week,'start_date':start,'end_date':start+timedelta(days=6),'working':saved.get(week,{}).get('working',1),'reason':saved.get(week,{}).get('reason','')})
            return rows

    def _reverse_credit(self,c,row,admin_id,reason):
        from .service import require
        student=one(c,'SELECT * FROM student WHERE student_id=%s FOR UPDATE',(row['student_id'],))
        score=student['credit_score']
        entries=all_rows(c,"""SELECT l.* FROM credit_log l JOIN violation v ON v.violation_id=l.violation_id
            WHERE v.attendance_id=%s AND v.status='VALID' AND l.entry_type='DEDUCTION'
            AND NOT EXISTS(SELECT 1 FROM credit_log r WHERE r.reverses_log_id=l.credit_log_id)""",(row['attendance_id'],))
        for e in entries:
            restore=-e['change_score'];require(score+restore<=2147483647,'信用分超出范围')
            c.execute('''INSERT INTO credit_log(student_id,violation_id,rule_id,operator_id,change_score,before_score,after_score,
                change_reason,change_time,entry_type,reverses_log_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'REVERSAL',%s)''',
                (row['student_id'],e['violation_id'],e['rule_id'],admin_id,restore,score,score+restore,reason,self.clock(),e['credit_log_id']))
            score+=restore
        c.execute("UPDATE violation SET status='REVOKED' WHERE attendance_id=%s AND status='VALID'",(row['attendance_id'],))
        if score!=student['credit_score']: self._set_credit_state(c,student,score)

    def set_business_week(self,actor,business_id,semester_id,week_no,working,reason):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,))
            require(b and b['code'] in ('GARDEN','PUBLICITY'),'该业务不支持按周停工',422)
            self.scope(a,b)
            term=one(c,'SELECT * FROM semester WHERE semester_id=%s',(semester_id,))
            require(term and 1<=week_no<=term['end_week'],'学期或周次无效',422)
            start=monday(term['start_date'])+timedelta(weeks=week_no-1)
            require(a['_role']=='SUPER' or start>=monday(self.clock().date()),'历史周须由超级管理员附原因更正',403)
            old=one(c,'SELECT * FROM business_week WHERE business_id=%s AND semester_id=%s AND week_no=%s',(business_id,semester_id,week_no))
            if old and bool(old['working'])==working: return {'replayed':True}
            c.execute('''INSERT INTO business_week(business_id,semester_id,week_no,working,reason,admin_id) VALUES(%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE working=VALUES(working),reason=VALUES(reason),admin_id=VALUES(admin_id)''',(business_id,semester_id,week_no,working,reason,a['_id']))
            rows=all_rows(c,'''SELECT s.*,at.attendance_id,at.attendance_status,at.source,at.revision,r.record_id,r.service_minutes,r.record_status,
                v.rule_id,v.nominal_deduct FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
                LEFT JOIN attendance at ON at.schedule_id=s.schedule_id LEFT JOIN service_record r ON r.attendance_id=at.attendance_id
                LEFT JOIN violation v ON v.attendance_id=at.attendance_id AND v.status='VALID'
                WHERE s.semester_id=%s AND s.week_no=%s AND t.business_id=%s''',(semester_id,week_no,business_id))
            changed=0
            for row in rows:
                sid=row['schedule_id']
                if not working and row['status']!='CANCELLED':
                    c.execute('INSERT INTO week_suspension(schedule_id,snapshot) VALUES(%s,%s) ON DUPLICATE KEY UPDATE snapshot=VALUES(snapshot)',(sid,json.dumps(row,default=str)))
                    c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='WEEK_OFF' WHERE schedule_id=%s",(sid,))
                    if row['attendance_id']:
                        self._reverse_credit(c,row,a['_id'],'业务停工冲正：'+reason)
                        c.execute("UPDATE service_record SET record_status='VOID',service_minutes=0 WHERE attendance_id=%s",(row['attendance_id'],))
                        c.execute("UPDATE attendance SET attendance_status='LEAVE',revision=revision+1,source='WEEK_OFF',remark=%s WHERE attendance_id=%s",(reason,row['attendance_id']))
                    changed+=1
                elif working and row['cancel_reason']=='WEEK_OFF':
                    snap=one(c,'SELECT snapshot FROM week_suspension WHERE schedule_id=%s',(sid,))
                    if not snap: continue
                    previous=json.loads(snap['snapshot'])
                    student=one(c,'SELECT * FROM student WHERE student_id=%s',(row['student_id'],))
                    # A stop cannot undo an independent quit, suspension or membership change.
                    if previous['status']=='ACTIVE' and student['status']!='ACTIVE': continue
                    c.execute('UPDATE schedule SET status=%s,cancel_reason=NULL WHERE schedule_id=%s',(previous['status'],sid))
                    if previous['attendance_id']:
                        c.execute('UPDATE attendance SET attendance_status=%s,source=%s,revision=revision+1 WHERE attendance_id=%s',(previous['attendance_status'],previous['source'],row['attendance_id']))
                        if previous['record_id']:
                            c.execute('UPDATE service_record SET service_minutes=%s,record_status=%s WHERE record_id=%s',(previous['service_minutes'],previous['record_status'],previous['record_id']))
                        if previous['rule_id']:
                            score=student['credit_score']; after=max(0,score-previous['nominal_deduct'])
                            c.execute('INSERT INTO violation(attendance_id,rule_id,nominal_deduct) VALUES(%s,%s,%s)',(row['attendance_id'],previous['rule_id'],previous['nominal_deduct']))
                            vid=c.lastrowid
                            c.execute('''INSERT INTO credit_log(student_id,violation_id,rule_id,operator_id,change_score,before_score,after_score,change_reason,change_time)
                                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(row['student_id'],vid,previous['rule_id'],a['_id'],after-score,score,after,'恢复上工周原考勤：'+reason,self.clock()))
                            self._set_credit_state(c,student,after)
                    c.execute('DELETE FROM week_suspension WHERE schedule_id=%s',(sid,));changed+=1
            result=self._sync_semester(c,semester_id)
            result.update(changed=changed,settled=self._settle_weeks(c)['settled'])
            self.audit(c,a['_id'],'SET_BUSINESS_WEEK','business',business_id,old,{'semester_id':semester_id,'week_no':week_no,'working':working,**result},reason)
            return result

    def _event_business(self,c,name):
        from .service import require
        name=name.strip();name='干部及干事' if name=='干部' else name;require(1<=len(name)<=100,'业务名称须为1至100字',422)
        b=one(c,'SELECT * FROM business WHERE name=%s',(name,))
        if b:
            require(b['kind']=='EVENT','固定业务不能通过专项导入绕过考勤',422)
            self._active_business(c,b['business_id'])
        else:
            c.execute("INSERT INTO business(name,kind,manager_scope) VALUES(%s,'EVENT','NONE')",(name,))
            b=one(c,'SELECT * FROM business WHERE business_id=%s',(c.lastrowid,))
            c.execute('INSERT INTO business_window(business_id,active_from) VALUES(%s,%s)',(b['business_id'],self.clock()))
        return b

    def _event_slot(self,c,business_id,title,duration):
        old=one(c,"SELECT slot_id FROM service_slot WHERE business_id=%s AND schedule_kind='EVENT' AND team_name=%s",(business_id,title))
        if old: return old['slot_id']
        c.execute('''INSERT INTO service_slot(business_id,schedule_kind,team_name,period_no,start_time,end_time,location,service_minutes,manager_admin_id)
            VALUES(%s,'EVENT',%s,1,NULL,NULL,'非固定业务',%s,NULL)''',(business_id,title,max(1,duration)))
        return c.lastrowid

    def _event_record(self,c,student_id,business_id,title,day,duration,admin_id,source,key,recognize=True):
        from .service import require
        require(0<=duration<=1440,'认定分钟须为0至1440的整数',422)
        old=one(c,'''SELECT s.*,t.business_id,t.team_name FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
            WHERE source_key=%s''',(key,))
        if old:
            require((old['student_id'],old['business_id'],old['team_name'],old['schedule_date'],old['recognition_minutes'])==
                    (student_id,business_id,title,day,duration),'该提交标识已用于其他内容，请刷新后重试')
            return old['schedule_id']
        slot=self._event_slot(c,business_id,title,duration)
        # The base ledger permits one active occurrence per student/slot/date. Separate source occurrences get distinct event slots.
        if one(c,"SELECT 1 FROM schedule WHERE student_id=%s AND slot_id=%s AND schedule_date=%s AND status IN ('ACTIVE','COMPLETED')",(student_id,slot,day)):
            c.execute('''INSERT INTO service_slot(business_id,schedule_kind,team_name,period_no,start_time,end_time,location,service_minutes,manager_admin_id)
                VALUES(%s,'EVENT',%s,1,NULL,NULL,'非固定业务',%s,NULL)''',(business_id,title,max(1,duration)));slot=c.lastrowid
        term=one(c,'SELECT * FROM semester WHERE start_date<=%s AND end_date>=%s',(day,day))
        week=(day-monday(term['start_date'])).days//7+1 if term else None
        c.execute('''INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date,semester_id,week_no,recognition_minutes,source_key)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',(student_id,slot,admin_id,day,term['semester_id'] if term else None,week,duration,key))
        sid=c.lastrowid
        if recognize:self._recognize(c,sid,admin_id,duration,source)
        if not one(c,'''SELECT 1 FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from<=%s
            AND (effective_until IS NULL OR effective_until>%s)''',(business_id,student_id,day,day)):
            following=one(c,'SELECT MIN(effective_from) AS day FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from>%s',(business_id,student_id,day))['day']
            c.execute('INSERT INTO business_member(business_id,student_id,effective_from,effective_until) VALUES(%s,%s,%s,%s)',(business_id,student_id,day,following))
        return sid

    def create_collection(self,actor,business_id,title,start_date,end_date,student_ids,items,attachments=None,submission_deadline=None,group_id=None):
        from .service import require,parse_date
        start,end=parse_date(start_date),parse_date(end_date)
        require(start<=end and items and student_ids,'请填写日期范围、参与名单和工作事项',422)
        require(1<=len(title.strip())<=100,'征集标题无效',422)
        deadline=parse_date(submission_deadline) if submission_deadline else None
        require(deadline is None or deadline>=end,'申报截止日期不能早于服务结束日期',422)
        with self.db.transaction() as c:self.actor(c,actor,('SUPER','NORMAL'))
        files=decode_attachments(attachments or [])
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'))
            b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,))
            require(b and b['kind']=='EVENT','请选择非固定业务',422)
            self._active_business(c,business_id)
            if group_id is not None:self._group(c,business_id,group_id)
            self._collection_scope(c,a,business_id,group_id)
            if group_id is not None:require(set(student_ids)<=self._group_people(c,group_id),'参与人员必须属于所选小组',403)
            if a['_role']=='NORMAL':
                allowed={p['student_id'] for p in self.collection_participants(actor,business_id if group_id else None,group_id=group_id)}
                require(set(student_ids)<=allowed,'参与人员超出你的征集管理范围',403)
            for sid in set(student_ids): require(one(c,"SELECT 1 FROM student WHERE student_id=%s AND status='ACTIVE'",(sid,)),f'队员 {sid} 不存在或不在队',422)
            c.execute('INSERT INTO hour_collection(business_id,title,start_date,end_date,admin_id,create_time) VALUES(%s,%s,%s,%s,%s,%s)',(business_id,title.strip(),start,end,a['_id'],self.clock()))
            cid=c.lastrowid
            c.execute('UPDATE hour_collection SET submission_deadline=%s,group_id=%s,minute_step=30 WHERE collection_id=%s',(deadline,group_id,cid))
            for sid in sorted(set(student_ids)): c.execute('INSERT INTO collection_person VALUES(%s,%s)',(cid,sid))
            for item in items:
                from .hour_units import validate_half_hour
                validate_half_hour(item['min_minutes']);validate_half_hour(item['max_minutes'])
                require(1<=len(item['title'].strip())<=100 and 0<=item['min_minutes']<=item['max_minutes']<=1440,'工作事项或分钟范围无效',422)
                c.execute('INSERT INTO collection_item(collection_id,title,min_minutes,max_minutes) VALUES(%s,%s,%s,%s)',(cid,item['title'].strip(),item['min_minutes'],item['max_minutes']))
            for f in files:
                c.execute('INSERT INTO collection_attachment(collection_id,filename,mime_type,size_bytes,content) VALUES(%s,%s,%s,%s,%s)',
                          (cid,f['filename'],f['mime_type'],f['size_bytes'],f['content']))
            self.audit(c,a['_id'],'CREATE_COLLECTION','hour_collection',cid,after={'title':title,'student_ids':sorted(set(student_ids)),'items':items,
                'attachments':[{'filename':f['filename'],'size_bytes':f['size_bytes']} for f in files]})
            recipients=[('student',sid) for sid in set(student_ids)]+self._super_recipients(c)+[('admin',m['admin_id']) for m in self._collection_admins(c,business_id,group_id)]
            self._notice(c,recipients,f'collection-published:{cid}','COLLECTION','新的时长征集已发布',title+'：请查看工作事项和申报截止日期。','collections',cid)
            return {'collection_id':cid}

    def collections(self,actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'))
            sql='SELECT h.*,b.name AS business_name,g.name AS group_name FROM hour_collection h JOIN business b ON b.business_id=h.business_id LEFT JOIN business_group g ON g.group_id=h.group_id';args=()
            if a['_role']=='STUDENT': sql+=' WHERE EXISTS(SELECT 1 FROM collection_person p WHERE p.collection_id=h.collection_id AND p.student_id=%s)';args=(a['_id'],)
            if a['_role']=='NORMAL': sql+=' WHERE (EXISTS(SELECT 1 FROM collection_manager m WHERE m.business_id=h.business_id AND m.admin_id=%s) OR EXISTS(SELECT 1 FROM collection_group_manager m WHERE m.group_id=h.group_id AND m.admin_id=%s))';args=(a['_id'],a['_id'])
            rows=list(all_rows(c,sql+' ORDER BY h.collection_id DESC',args))
            for r in rows:
                r['can_submit']=a['_role']=='STUDENT' and self._collection_open(r) and a['status']=='ACTIVE'
                r['can_manage']=a['_role'] in ('NORMAL','SUPER')
                r['effective_status']='OPEN' if self._collection_open(r) else 'CLOSED'
                managers=self._collection_admins(c,r['business_id'],r.get('group_id'))
                r['attachments']=all_rows(c,'SELECT attachment_id,filename,mime_type,size_bytes FROM collection_attachment WHERE collection_id=%s ORDER BY attachment_id',(r['collection_id'],))
                r['items']=all_rows(c,'SELECT * FROM collection_item WHERE collection_id=%s',(r['collection_id'],))
                r['submissions']=all_rows(c,'''SELECT s.*,st.name,i.title AS item_title FROM hour_submission s
                    JOIN collection_item i ON i.item_id=s.item_id JOIN student st ON st.student_id=s.student_id
                    WHERE i.collection_id=%s'''+(' AND s.student_id=%s' if a['_role']=='STUDENT' else ''),(r['collection_id'],a['_id']) if a['_role']=='STUDENT' else (r['collection_id'],))
                for sub in r['submissions']:
                    sub['attachments']=all_rows(c,'SELECT attachment_id,filename,mime_type,size_bytes FROM submission_attachment WHERE submission_id=%s AND submission_revision=%s ORDER BY attachment_id',(sub['submission_id'],sub['attachment_revision']))
                    sub['reviews']=all_rows(c,'SELECT r.review_id,r.revision,r.stage,r.approved,r.service_minutes,r.reason,r.created_at,a.name AS admin_name FROM submission_review r JOIN admin a ON a.admin_id=r.admin_id WHERE submission_id=%s ORDER BY r.revision',(sub['submission_id'],))
                    sub['can_review']=a['_role']=='NORMAL' and sub['status']=='PENDING' or a['_role']=='SUPER' and (sub['status']=='FIRST_APPROVED' or sub['status']=='PENDING' and not managers)
                    sub['can_correct']=a['_role']=='SUPER' and sub['status'] in ('APPROVED','REJECTED')
            return rows

    def create_event(self,actor,business_name,student_id,title,service_date,service_minutes,reason,request_key):
        from .service import require,parse_date,reason_text
        reason=reason_text(reason);day=parse_date(service_date)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            require(one(c,"SELECT 1 FROM student WHERE student_id=%s AND status='ACTIVE'",(student_id,)),'队员不存在或不在队',422)
            b=self._event_business(c,business_name)
            sid=self._event_record(c,student_id,b['business_id'],title,day,service_minutes,a['_id'],'MANUAL_EVENT','manual:'+request_key,recognize=day<=self.clock().date())
            self.audit(c,a['_id'],'CREATE_EVENT','schedule',sid,after={'service_minutes':service_minutes},reason=reason)
            return {'schedule_id':sid}

    def recognize_event(self,actor,schedule_id,service_minutes,reason):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));row=self.schedule(c,schedule_id)
            require(row['schedule_kind']=='EVENT' and (row['source_key'] or '').startswith('manual:'),'仅适用于手动临时排班',422)
            require(type(service_minutes)==int and 0<=service_minutes<=1440,'分钟数须为0至1440的整数',422)
            require(row['schedule_date']<=self.clock().date(),'服务日期尚未到达，不能认定时长',422)
            if row['status']=='COMPLETED':
                require(row['recognition_minutes']==service_minutes,'已经认定，请在服务时长页面附原因修正')
                return {'replayed':True}
            require(row['status']=='ACTIVE','该排班已取消')
            c.execute('UPDATE schedule SET recognition_minutes=%s WHERE schedule_id=%s',(service_minutes,schedule_id))
            self._recognize(c,schedule_id,a['_id'],service_minutes,'MANUAL_EVENT')
            self.audit(c,a['_id'],'RECOGNIZE_EVENT','schedule',schedule_id,after={'service_minutes':service_minutes},reason=reason)
            return {'schedule_id':schedule_id,'service_minutes':service_minutes}

    def set_event_member(self,actor,business_id,student_id,active,effective_date,reason):
        from .service import require,parse_date,reason_text
        reason=reason_text(reason);day=parse_date(effective_date)
        require(day>=self.clock().date(),'不能追溯改写业务归属',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,))
            require(b and b['kind']=='EVENT','固定业务请通过时段归属调整',422)
            self._active_business(c,business_id)
            require(one(c,"SELECT 1 FROM student WHERE student_id=%s AND status='ACTIVE'",(student_id,)),'队员不存在或不在队',422)
            old=all_rows(c,'SELECT * FROM business_member WHERE business_id=%s AND student_id=%s',(business_id,student_id))
            # Replace only plans on/after the new effective date; retain earlier history.
            c.execute('DELETE FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from>=%s',(business_id,student_id,day))
            c.execute('UPDATE business_member SET effective_until=%s WHERE business_id=%s AND student_id=%s AND effective_from<%s AND (effective_until IS NULL OR effective_until>%s)',(day,business_id,student_id,day,day))
            if not active:
                c.execute('DELETE FROM group_member WHERE student_id=%s AND group_id IN (SELECT group_id FROM business_group WHERE business_id=%s) AND effective_from>=%s',(student_id,business_id,day))
                c.execute('UPDATE group_member SET effective_until=%s WHERE student_id=%s AND group_id IN (SELECT group_id FROM business_group WHERE business_id=%s) AND effective_from<%s AND (effective_until IS NULL OR effective_until>%s)',(day,student_id,business_id,day,day))
            if active:c.execute('INSERT INTO business_member(business_id,student_id,effective_from) VALUES(%s,%s,%s)',(business_id,student_id,day))
            self.audit(c,a['_id'],'SET_BUSINESS_MEMBER','business',business_id,old,{'student_id':student_id,'active':active,'effective_date':day},reason)
            return {'business_id':business_id,'student_id':student_id,'active':active}

    def apply_leave(self,actor,schedule_id,reason,images=None):
        from .service import require,reason_text
        with self.db.transaction() as c:multi=installed(c)
        if not multi:return self._legacy_apply_leave(actor,schedule_id,reason)
        reason=reason_text(reason);require(images and 1<=len(images)<=3,'请上传1至3张请假证明图片',422)
        decoded=[]
        for image in images:
            try: data=base64.b64decode(image,validate=True)
            except Exception: require(False,'图片编码无效',422)
            require(len(data)<=2*1024*1024,'每张图片不超过2MB',422)
            from PIL import Image
            from io import BytesIO
            try:
                with Image.open(BytesIO(data)) as img:
                    require(img.format in ('PNG','JPEG') and img.width*img.height<=20000000,'仅支持有效PNG/JPEG图片，最大2000万像素',422)
                    mime='image/png' if img.format=='PNG' else 'image/jpeg';img.verify()
            except Exception as e:
                from .service import DomainError
                if isinstance(e,DomainError):raise
                require(False,'无法读取证明图片',422)
            decoded.append((mime,data))
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('STUDENT',),True);row=self.schedule(c,schedule_id);self.scope(a,row)
            require(row.get('schedule_kind')!='EVENT','非固定时长事项不通过此入口请假',422)
            self.future_schedule(row);self.pending_guard(c,schedule_id)
            c.execute('INSERT INTO leave_application(student_id,schedule_id,reason) VALUES(%s,%s,%s)',(a['_id'],schedule_id,reason));lid=c.lastrowid
            for mime,data in decoded:c.execute('INSERT INTO leave_attachment(leave_id,mime_type,content) VALUES(%s,%s,%s)',(lid,mime,data))
            self.notify_application(c,'leave_application',lid)
            return {'leave_id':lid}

    def approve_leave(self,actor,leave_id,approved,reason=''):
        from .service import require,reason_text
        with self.db.transaction() as c:multi=installed(c)
        if not multi:return self._legacy_approve_leave(actor,leave_id,approved)
        if not approved:reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('NORMAL',));app=one(c,'SELECT * FROM leave_application WHERE leave_id=%s FOR UPDATE',(leave_id,))
            require(app,'申请不存在',404);row=self.schedule(c,app['schedule_id']);self.scope(a,row,True)
            desired='APPROVED' if approved else 'REJECTED'
            if app['approve_status']==desired:return {'replayed':True,'status':desired}
            require(app['approve_status']=='PENDING','申请已处理');self.future_schedule(row)
            c.execute('UPDATE leave_application SET approve_status=%s,approve_admin_id=%s,approve_time=%s,rejection_reason=%s WHERE leave_id=%s',(desired,a['_id'],self.clock(),reason,leave_id))
            self.audit(c,a['_id'],'APPROVE_LEAVE','leave_application',leave_id,app,{'status':desired},reason)
            return {'status':desired}

    def leave_evidence(self,actor,leave_id,attachment_id=None):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor);app=one(c,'SELECT * FROM leave_application WHERE leave_id=%s',(leave_id,))
            require(app,'申请不存在',404);self.scope(a,self.schedule(c,app['schedule_id']))
            if attachment_id is None:return all_rows(c,'SELECT attachment_id,mime_type FROM leave_attachment WHERE leave_id=%s',(leave_id,))
            row=one(c,'SELECT mime_type,content FROM leave_attachment WHERE leave_id=%s AND attachment_id=%s',(leave_id,attachment_id))
            require(row,'图片不存在',404);return row
