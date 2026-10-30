"""Business catalogue, reversible lifecycle and dated group membership."""
from datetime import datetime,time,timedelta
from .db import one,all_rows
from .inbox import InboxService
from .directory_schema import installed
from .member_import import MemberImport


class DirectoryManagement(MemberImport,InboxService):
    def _active_business(self,c,business_id):
        from .service import require
        b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,))
        require(b,'业务不存在',404);require(b.get('status','ACTIVE')=='ACTIVE','业务已归档，请先恢复后再操作',422)
        return b

    def _group(self,c,business_id,group_id):
        from .service import require
        g=one(c,'SELECT * FROM business_group WHERE group_id=%s AND business_id=%s',(group_id,business_id))
        require(g,'小组不属于该业务',422);return g

    def _group_people(self,c,group_id):
        return {r['student_id'] for r in all_rows(c,"""SELECT m.student_id FROM group_member m JOIN student s ON s.student_id=m.student_id
            WHERE m.group_id=%s AND m.effective_from<=%s AND (m.effective_until IS NULL OR m.effective_until>%s) AND s.status='ACTIVE'""",
            (group_id,self.clock().date(),self.clock().date()))}

    def create_business(self,actor,name,kind,slots=None):
        from .service import require
        name=name.strip();require(1<=len(name)<=100 and name!='干部','请填写有效且不重复的业务名称',422)
        require(kind in ('FIXED','EVENT'),'业务类型无效',422)
        require(kind=='EVENT' or slots,'固定业务须至少配置一个时段',422)
        require(kind=='FIXED' or not slots,'非固定业务不配置每周时段',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));require(not one(c,'SELECT 1 FROM business WHERE name=%s',(name,)),'业务已存在（含归档业务），请勿重复创建',409)
            c.execute('INSERT INTO business(name,kind,manager_scope) VALUES(%s,%s,%s)',(name,kind,'SLOT' if kind=='FIXED' else 'NONE'));bid=c.lastrowid
            c.execute('INSERT INTO business_window(business_id,active_from) VALUES(%s,%s)',(bid,self.clock()))
            for slot in slots or []:self._add_business_slot(c,bid,slot)
            self.audit(c,a['_id'],'CREATE_BUSINESS','business',bid,after={'name':name,'kind':kind,'slots':slots or []})
            return {'business_id':bid}

    def _add_business_slot(self,c,bid,slot):
        from .service import require,minutes
        b=self._active_business(c,bid);require(b['kind']=='FIXED','只支持固定排班业务',422)
        day,period=slot['weekday'],slot['period_no'];start,end=time.fromisoformat(str(slot['start_time'])),time.fromisoformat(str(slot['end_time']))
        require(1<=day<=7 and 1<=period<=100 and minutes(start)<minutes(end),'星期、时段编号或起止时间无效；不支持跨日',422)
        require(1<=slot['service_minutes']<=1440 and 1<=slot['need_num']<=10000,'认定分钟或容量无效',422)
        self.actor(c,{'kind':'admin','id':slot['manager_admin_id']},('NORMAL',))
        others=all_rows(c,"SELECT * FROM service_slot WHERE business_id=%s AND weekday=%s AND status='ACTIVE'",(bid,day))
        require(not any(r['period_no']==period or minutes(r['start_time'])<minutes(end) and minutes(start)<minutes(r['end_time']) for r in others),'时段编号重复或业务内时间重叠',422)
        c.execute('''INSERT INTO service_slot(business_id,schedule_kind,team_name,weekday,period_no,start_time,end_time,location,need_num,service_minutes,manager_admin_id)
          VALUES(%s,'FIXED',%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(bid,f'{b["name"]} · 周{"一二三四五六日"[day-1]}第{period}时段',day,period,start,end,slot.get('location') or b['name'],slot['need_num'],slot['service_minutes'],slot['manager_admin_id']))
        return c.lastrowid

    def add_business_slot(self,actor,business_id,**slot):
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));sid=self._add_business_slot(c,business_id,slot)
            self.audit(c,a['_id'],'ADD_BUSINESS_SLOT','service_slot',sid,after=slot)
            return {'slot_id':sid}

    def rename_business(self,actor,business_id,name,reason):
        from .service import require,reason_text
        name=name.strip();reason=reason_text(reason)
        require(1<=len(name)<=100 and name!='干部','业务名称无效',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,));require(b,'业务不存在',404)
            require(not one(c,'SELECT 1 FROM business WHERE name=%s AND business_id<>%s',(name,business_id)),'业务名称已存在',409)
            require(b['name']!='干部及干事' or name==b['name'],'干部及干事是内置分组业务，名称保持不变',422)
            c.execute('UPDATE business SET name=%s,revision=revision+1 WHERE business_id=%s',(name,business_id))
            # Slot labels are display values; preserve identifiers and record amounts.
            c.execute("UPDATE service_slot SET team_name=REPLACE(team_name,%s,%s) WHERE business_id=%s AND schedule_kind='FIXED'",(b['name']+' · ',name+' · ',business_id))
            self.audit(c,a['_id'],'RENAME_BUSINESS','business',business_id,{'name':b['name']},{'name':name},reason)
            return {'name':name}

    def _archive_impact(self,c,bid):
        import json
        blockers=[]
        slots={r['slot_id'] for r in all_rows(c,'SELECT slot_id FROM service_slot WHERE business_id=%s',(bid,))}
        for r in all_rows(c,"SELECT change_id,slot_ids FROM membership_change WHERE status='PENDING'"):
            if slots.intersection(json.loads(r['slot_ids'])):blockers.append({'kind':'待生效归属调整','id':r['change_id']})
        for r in all_rows(c,"SELECT collection_id,title FROM hour_collection WHERE business_id=%s AND status='OPEN'",(bid,)):blockers.append({'kind':'开放征集','id':r['collection_id'],'label':r['title']})
        for r in all_rows(c,"""SELECT s.submission_id FROM hour_submission s JOIN collection_item i ON i.item_id=s.item_id
          JOIN hour_collection h ON h.collection_id=i.collection_id WHERE h.business_id=%s AND s.status IN ('PENDING','FIRST_APPROVED')""",(bid,)):blockers.append({'kind':'待审核申报','id':r['submission_id']})
        for r in all_rows(c,"""SELECT p.leave_id FROM leave_application p JOIN schedule s ON s.schedule_id=p.schedule_id
          JOIN service_slot t ON t.slot_id=s.slot_id WHERE t.business_id=%s AND p.approve_status='PENDING'""",(bid,)):blockers.append({'kind':'待审批请假','id':r['leave_id']})
        for r in all_rows(c,"""SELECT p.transfer_id FROM transfer_application p JOIN service_slot old ON old.slot_id=p.old_slot_id
          JOIN service_slot new ON new.slot_id=p.new_slot_id WHERE (old.business_id=%s OR new.business_id=%s)
          AND p.final_status='PENDING' AND p.first_status IN ('PENDING','APPROVED')""",(bid,bid)):blockers.append({'kind':'待审批换班','id':r['transfer_id']})
        for r in all_rows(c,"""SELECT DISTINCT p.withdrawal_id FROM withdrawal_application p WHERE p.approve_status='PENDING' AND
          (EXISTS(SELECT 1 FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id WHERE m.student_id=p.student_id AND t.business_id=%s)
          OR EXISTS(SELECT 1 FROM business_member m WHERE m.student_id=p.student_id AND m.business_id=%s AND m.effective_from<=%s AND (m.effective_until IS NULL OR m.effective_until>%s)))""",(bid,bid,self.clock().date(),self.clock().date())):blockers.append({'kind':'待审批退队','id':r['withdrawal_id']})
        for r in all_rows(c,"SELECT request_id FROM collection_scope_request WHERE business_id=%s AND status='PENDING'",(bid,)):blockers.append({'kind':'待审批管理范围','id':r['request_id']})
        rows=all_rows(c,"SELECT s.*,t.schedule_kind,t.start_time FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id WHERE t.business_id=%s AND s.status='ACTIVE'",(bid,))
        future=[r for r in rows if self._not_started(r)]
        return {'blockers':blockers,'future_count':len(future),'future_schedules':future}

    def _not_started(self,row):
        from .service import instant
        from .semester import monday
        if row['schedule_kind']=='WEEKLY':return monday(row['schedule_date'])>monday(self.clock().date())
        if row['start_time'] is None:return row['schedule_date']>self.clock().date()
        return instant(row['schedule_date'],row['start_time'])>self.clock()

    def archive_impact(self,actor,business_id):
        from .service import require
        with self.db.transaction() as c:
            self.actor(c,actor,('SUPER',));b=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,));require(b,'业务不存在',404)
            result=self._archive_impact(c,business_id);result.pop('future_schedules');return {**result,'revision':b['revision'],'status':b['status']}

    def change_business_status(self,actor,business_id,active,expected_revision,reason):
        from .service import require,reason_text
        reason=reason_text(reason);desired='ACTIVE' if active else 'ARCHIVED'
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));b=one(c,'SELECT * FROM business WHERE business_id=%s FOR UPDATE',(business_id,));require(b,'业务不存在',404)
            if b['status']==desired and b['revision']==expected_revision+1:return {'replayed':True}
            require(b['revision']==expected_revision and b['status']!=desired,'业务状态已改变，请刷新',409)
            if not active:
                impact=self._archive_impact(c,business_id);require(not impact['blockers'],'请先处理归档预览列出的申请、征集或申报',409)
                c.execute('UPDATE business_window SET active_until=%s WHERE business_id=%s AND active_until IS NULL',(self.clock(),business_id))
                for r in impact['future_schedules']:
                    c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='BUSINESS_ARCHIVED' WHERE schedule_id=%s",(r['schedule_id'],))
                    c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(r['schedule_id'],))
                    self._notice(c,[('student',r['student_id'])],f'business-archived:{business_id}:{b["revision"]}:{r["schedule_id"]}','SERVICE','业务停用，未来排班已取消',b['name']+'：'+reason,'schedules',r['schedule_id'])
            else:
                c.execute('INSERT INTO business_window(business_id,active_from) VALUES(%s,%s)',(business_id,self.clock()))
                rows=all_rows(c,"SELECT s.*,t.schedule_kind,t.start_time FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id JOIN student st ON st.student_id=s.student_id WHERE t.business_id=%s AND s.status='CANCELLED' AND s.cancel_reason='BUSINESS_ARCHIVED' AND st.status='ACTIVE'",(business_id,))
                for r in rows:
                    if self._not_started(r):
                        if r['schedule_kind']=='EVENT':
                            occupied=one(c,"SELECT 1 FROM schedule WHERE student_id=%s AND slot_id=%s AND schedule_date=%s AND status IN ('ACTIVE','COMPLETED')",(r['student_id'],r['slot_id'],r['schedule_date']))
                            if not occupied:c.execute("UPDATE schedule SET status='ACTIVE',cancel_reason=NULL WHERE schedule_id=%s",(r['schedule_id'],))
                        else:c.execute("UPDATE schedule SET cancel_reason='SYNC' WHERE schedule_id=%s",(r['schedule_id'],))
            c.execute('UPDATE business SET status=%s,revision=revision+1 WHERE business_id=%s',(desired,business_id))
            self.sync_semesters(c)
            self.audit(c,a['_id'],'RESTORE_BUSINESS' if active else 'ARCHIVE_BUSINESS','business',business_id,{'status':b['status']},{'status':desired},reason)
            return {'status':desired}

    def business_groups(self,actor,business_id=None):
        with self.db.transaction() as c:
            a=self.actor(c,actor);sql='SELECT g.*,b.name AS business_name,b.status AS business_status FROM business_group g JOIN business b ON b.business_id=g.business_id';args=[]
            if business_id:sql+=' WHERE g.business_id=%s';args.append(business_id)
            rows=list(all_rows(c,sql+' ORDER BY g.group_id',args))
            for r in rows:
                r['can_manage']=a['_role']=='SUPER' or a['_role']=='NORMAL' and bool(one(c,'SELECT 1 FROM collection_manager WHERE admin_id=%s AND business_id=%s',(a['_id'],r['business_id'])) or one(c,'SELECT 1 FROM collection_group_manager WHERE admin_id=%s AND group_id=%s',(a['_id'],r['group_id'])))
                r['member_count']=len(self._group_people(c,r['group_id']))
            return rows

    def group_members(self,actor,group_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'));g=one(c,'SELECT * FROM business_group WHERE group_id=%s',(group_id,));require(g,'小组不存在',404)
            self._collection_scope(c,a,g['business_id'],group_id)
            return all_rows(c,"""SELECT m.*,s.name,s.college,s.status FROM group_member m JOIN student s ON s.student_id=m.student_id
                WHERE group_id=%s ORDER BY s.student_id,m.effective_from""",(group_id,))

    def _join_business(self,c,bid,sid,day):
        if not one(c,'SELECT 1 FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from<=%s AND (effective_until IS NULL OR effective_until>%s)',(bid,sid,day,day)):
            following=one(c,'SELECT MIN(effective_from) day FROM business_member WHERE business_id=%s AND student_id=%s AND effective_from>%s',(bid,sid,day))['day']
            c.execute('INSERT INTO business_member(business_id,student_id,effective_from,effective_until) VALUES(%s,%s,%s,%s)',(bid,sid,day,following))

    def _join_group(self,c,gid,sid,day):
        if not one(c,'SELECT 1 FROM group_member WHERE group_id=%s AND student_id=%s AND effective_from<=%s AND (effective_until IS NULL OR effective_until>%s)',(gid,sid,day,day)):
            following=one(c,'SELECT MIN(effective_from) day FROM group_member WHERE group_id=%s AND student_id=%s AND effective_from>%s',(gid,sid,day))['day']
            c.execute('INSERT INTO group_member(group_id,student_id,effective_from,effective_until) VALUES(%s,%s,%s,%s)',(gid,sid,day,following))

    def set_group_member(self,actor,group_id,student_id,active,effective_date,reason):
        from .service import require,reason_text,parse_date
        reason=reason_text(reason);day=parse_date(effective_date);require(day>=self.clock().date(),'不能追改历史小组归属',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));g=one(c,'SELECT * FROM business_group WHERE group_id=%s',(group_id,));require(g,'小组不存在',404);self._active_business(c,g['business_id'])
            require(one(c,"SELECT 1 FROM student WHERE student_id=%s AND status='ACTIVE'",(student_id,)),'队员不存在或不在队',422)
            c.execute('DELETE FROM group_member WHERE group_id=%s AND student_id=%s AND effective_from>=%s',(group_id,student_id,day))
            c.execute('UPDATE group_member SET effective_until=%s WHERE group_id=%s AND student_id=%s AND effective_from<%s AND (effective_until IS NULL OR effective_until>%s)',(day,group_id,student_id,day,day))
            if active:self._join_business(c,g['business_id'],student_id,day);self._join_group(c,group_id,student_id,day)
            self.audit(c,a['_id'],'SET_GROUP_MEMBER','business_group',group_id,after={'student_id':student_id,'active':active,'effective_date':day},reason=reason)
            return {'group_id':group_id}
