"""Business scopes and weekly work, sharing the existing accounting ledger."""
import json
from datetime import datetime, time, timedelta
from .db import one, all_rows
from .business_schema import installed
from .semester import monday
from .business_workflows import BusinessWorkflows
from .specialty import SpecialtyService


class BusinessService(BusinessWorkflows, SpecialtyService):
    def students(self,actor,student_id=None):
        rows=self._legacy_students(actor,student_id)
        with self.db.transaction() as c:
            if not installed(c):return rows
            links=all_rows(c,'''SELECT DISTINCT m.student_id,t.business_id FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id
                UNION SELECT student_id,business_id FROM business_member WHERE effective_from<=%s AND (effective_until IS NULL OR effective_until>%s)''',(self.clock().date(),self.clock().date()))
            by_id={r['student_id']:r for r in rows}
            for r in rows:r['business_ids']=[]
            for link in links:
                if link['student_id'] in by_id:by_id[link['student_id']]['business_ids'].append(link['business_id'])
            group_links=all_rows(c,'''SELECT m.student_id,g.group_id,g.business_id,g.name FROM group_member m JOIN business_group g ON g.group_id=m.group_id
                WHERE m.effective_from<=%s AND (m.effective_until IS NULL OR m.effective_until>%s)''',(self.clock().date(),self.clock().date()))
            for r in rows:r['groups']=[]
            for link in group_links:
                if link['student_id'] in by_id:by_id[link['student_id']]['groups'].append(link)
        return rows

    def businesses(self, actor):
        with self.db.transaction() as c:
            a = self.actor(c,actor)
            if not installed(c): return []
            rows = list(all_rows(c,'SELECT * FROM business ORDER BY business_id'))
            from .collection_governance_schema import installed as governance_installed
            collect_ids={r['business_id'] for r in all_rows(c,'SELECT business_id FROM collection_manager WHERE admin_id=%s',(a['_id'],))} if a['_role']=='NORMAL' and governance_installed(c) else set()
            for row in rows:
                row['can_collect_all']=a['_role']=='SUPER' or row['business_id'] in collect_ids
                row['can_collect']=row['can_collect_all'] or a['_role']=='NORMAL' and bool(one(c,'SELECT 1 FROM collection_group_manager m JOIN business_group g ON g.group_id=m.group_id WHERE m.admin_id=%s AND g.business_id=%s',(a['_id'],row['business_id'])))
                row['can_manage'] = a['_role']=='SUPER' or a['_role']=='NORMAL' and row['manager_admin_id']==a['_id']
            return rows

    def configure_business(self, actor, business_id, manager_admin_id):
        from .service import require
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            biz=one(c,'SELECT * FROM business WHERE business_id=%s',(business_id,))
            require(biz and biz['manager_scope']=='BUSINESS','该业务按时段管理或无需普通管理员',422)
            if manager_admin_id is not None:
                require(one(c,"SELECT 1 FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",(manager_admin_id,)), '请选择有效普通管理员',422)
            c.execute('UPDATE business SET manager_admin_id=%s WHERE business_id=%s',(manager_admin_id,business_id))
            # Mirror scope onto slots so existing approval/listing permission checks stay effective.
            c.execute('UPDATE service_slot SET manager_admin_id=%s WHERE business_id=%s',(manager_admin_id,business_id))
            self.audit(c,a['_id'],'CONFIGURE_BUSINESS','business',business_id,biz,{'manager_admin_id':manager_admin_id})
            return {'business_id':business_id}

    def slot(self,c,slot_id):
        row=self._legacy_slot(c,slot_id)
        if installed(c):
            biz=one(c,'SELECT * FROM business WHERE business_id=%s',(row['business_id'],))
            row.update(business_name=biz['name'],business_code=biz['code'])
        return row

    def schedule(self,c,schedule_id):
        row=self._legacy_schedule(c,schedule_id)
        if installed(c):
            slot=self.slot(c,row['slot_id'])
            row.update({k:slot[k] for k in ('business_id','business_name','business_code','schedule_kind')})
            if row['recognition_minutes'] is not None: row['service_minutes']=row['recognition_minutes']
        return row

    def list_slots(self,actor):
        rows=self._legacy_list_slots(actor)
        with self.db.transaction() as c:
            if installed(c):
                lookup={b['business_id']:b for b in all_rows(c,'SELECT * FROM business')}
                for row in rows:
                    b=lookup[row['business_id']]
                    row.update(business_name=b['name'],business_code=b['code'],business_status=b.get('status','ACTIVE'))
        return rows

    def my_transfer_options(self,actor,old_slot_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('STUDENT',),True)
            require(one(c,'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id=%s',(a['_id'],old_slot_id)),
                    '原固定班次不属于本人',403)
            old=self.slot(c,old_slot_id)
            self._active_business(c,old['business_id'])
            require(old['status']=='ACTIVE' and old.get('schedule_kind') in ('FIXED','WEEKLY'),'原固定班次已停用或不支持换班',422)
            return all_rows(c,'''SELECT t.slot_id,t.team_name,t.business_id,t.schedule_kind,t.weekday,t.period_no,t.start_time,t.end_time
                FROM service_slot t WHERE t.business_id=%s AND t.status='ACTIVE' AND t.schedule_kind IN ('FIXED','WEEKLY')
                AND NOT EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=%s AND m.slot_id=t.slot_id)
                ORDER BY t.weekday,t.period_no''',(old['business_id'],a['_id']))

    def list_schedules(self,actor):
        rows=self._legacy_list_schedules(actor)
        with self.db.transaction() as c:
            if installed(c):
                lookup={r['slot_id']:r for r in all_rows(c,'''SELECT t.slot_id,t.schedule_kind,t.business_id,b.name AS business_name
                    FROM service_slot t JOIN business b ON b.business_id=t.business_id''')}
                amounts={r['schedule_id']:r['current_minutes'] for r in all_rows(c,'''SELECT s.schedule_id,
                    COALESCE(r.service_minutes,s.recognition_minutes,t.service_minutes) AS current_minutes
                    FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
                    LEFT JOIN attendance a ON a.schedule_id=s.schedule_id
                    LEFT JOIN service_record r ON r.attendance_id=a.attendance_id AND r.record_status='VALID' ''')}
                for row in rows:
                    row.update(lookup[row['slot_id']])
                    row['current_minutes']=amounts[row['schedule_id']]
        return rows

    def attendance_kind_guard(self,row,status):
        from .service import require
        require(row.get('schedule_kind')!='EVENT','专项及申报时长请通过服务记录修正，不能登记出勤处罚',422)
        require(row.get('schedule_kind')!='WEEKLY' or status!='LATE','开心花园没有迟到认定',422)

    def _snapshot_members(self,c,term):
        if not installed(c): return super()._snapshot_members(c,term)
        now=getattr(self,'_membership_effective',self.clock())
        current={(r['student_id'],r['slot_id']) for r in all_rows(c,"""SELECT m.* FROM slot_member m
            JOIN student s ON s.student_id=m.student_id JOIN service_slot t ON t.slot_id=m.slot_id
            WHERE s.status='ACTIVE' AND t.status='ACTIVE' AND t.schedule_kind IN ('FIXED','WEEKLY')""")}
        open_rows=all_rows(c,'SELECT * FROM semester_member WHERE semester_id=%s AND effective_until IS NULL',(term['semester_id'],))
        previous={(r['student_id'],r['slot_id']) for r in open_rows}
        effective=datetime.combine(term['start_date'],time())
        if term['members_initialized']: effective=max(effective,now)
        for r in open_rows:
            if (r['student_id'],r['slot_id']) not in current:
                c.execute('UPDATE semester_member SET effective_until=%s WHERE membership_id=%s',(max(effective,r['effective_from']),r['membership_id']))
        for sid,slot in current-previous:
            c.execute('INSERT INTO semester_member(semester_id,student_id,slot_id,effective_from) VALUES(%s,%s,%s,%s)',(term['semester_id'],sid,slot,effective))
        c.execute('UPDATE semester SET members_initialized=1 WHERE semester_id=%s',(term['semester_id'],))

    def _validate_memberships(self,c,student_id,slot_ids):
        from .service import require, minutes
        slots=[self.slot(c,s) for s in sorted(set(slot_ids))]
        for slot in slots:
            if not one(c,'SELECT 1 FROM slot_member WHERE slot_id=%s AND student_id=%s',(slot['slot_id'],student_id)):self._active_business(c,slot['business_id'])
        require(all(s['status']=='ACTIVE' and s['schedule_kind'] in ('FIXED','WEEKLY') for s in slots),'请选择有效固定时段或开心花园岗位',422)
        codes={s['business_code'] for s in slots}
        consult_days={s['weekday'] for s in slots if s['business_code']=='CONSULT'}
        previous_days={r['weekday'] for r in all_rows(c,'''SELECT t.weekday FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id
            JOIN business b ON b.business_id=t.business_id WHERE m.student_id=%s AND b.code='CONSULT' ''',(student_id,))}
        require(len(consult_days)<=1 or len(previous_days)>1 and consult_days<=previous_days,
                '咨询服务队员只能属于一个分队；历史跨队名单只能保留或缩小范围，不能新增分队',422)
        require(not {'CONSULT','ART'}<=codes,'咨询服务与美育不能同时归属',422)
        require(sum(s['schedule_kind']=='WEEKLY' for s in slots)<=1,'开心花园只能选择一个 A/B 岗位',422)
        for i,s in enumerate(slots):
            for other in slots[i+1:]:
                if s['schedule_kind']==other['schedule_kind']=='FIXED' and s['weekday']==other['weekday']:
                    require(not(minutes(s['start_time'])<minutes(other['end_time']) and minutes(other['start_time'])<minutes(s['end_time'])),'所选固定时段时间冲突',422)
        return slots

    def _replace_memberships(self,c,student_id,slot_ids,admin_id,reason):
        from .service import instant
        self._validate_memberships(c,student_id,slot_ids)
        self.snapshot_memberships(c)
        before=all_rows(c,'SELECT slot_id FROM slot_member WHERE student_id=%s',(student_id,))
        c.execute('DELETE FROM slot_member WHERE student_id=%s',(student_id,))
        for slot in sorted(set(slot_ids)):
            c.execute('INSERT INTO slot_member(student_id,slot_id) VALUES(%s,%s)',(student_id,slot))
        cutoff=getattr(self,'_membership_effective',self.clock())
        removed={r['slot_id'] for r in before}-set(slot_ids)
        for row in all_rows(c,"""SELECT s.*,t.start_time FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
            WHERE s.student_id=%s AND s.status='ACTIVE'""",(student_id,)):
            if row['slot_id'] in removed and instant(row['schedule_date'],row['start_time'])>=cutoff:
                c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='MEMBERSHIP' WHERE schedule_id=%s",(row['schedule_id'],))
                c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(row['schedule_id'],))
        c.execute("""UPDATE transfer_application p SET final_status='CANCELLED' WHERE student_id=%s
            AND old_slot_id IS NOT NULL AND final_status='PENDING' AND first_status<>'REJECTED'
            AND NOT EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=p.student_id AND m.slot_id=p.old_slot_id)""",(student_id,))
        self.snapshot_memberships(c)
        self.audit(c,admin_id,'SET_MEMBERSHIPS','student',student_id,{'slots':[r['slot_id'] for r in before]}, {'slots':slot_ids},reason)

    def set_memberships(self,actor,student_id,slot_ids,effective_date=None,reason='超级管理员调整业务归属'):
        from .service import require,parse_date,reason_text
        with self.db.transaction() as c: multi=installed(c)
        if not multi: return self._legacy_set_memberships(actor,student_id,slot_ids)
        day=parse_date(effective_date) if effective_date else self.clock().date()
        require(day>=self.clock().date(),'归属调整不能追溯改写历史',422)
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            require(one(c,"SELECT 1 FROM student WHERE student_id=%s AND status='ACTIVE'",(student_id,)),'队员不存在或不在队',422)
            self._validate_memberships(c,student_id,slot_ids)
            c.execute("UPDATE membership_change SET status='CANCELLED' WHERE student_id=%s AND status='PENDING'",(student_id,))
            if day>self.clock().date():
                c.execute('INSERT INTO membership_change(student_id,effective_date,slot_ids,admin_id,reason) VALUES(%s,%s,%s,%s,%s)',(student_id,day,json.dumps(slot_ids),a['_id'],reason))
                self.audit(c,a['_id'],'PLAN_MEMBERSHIPS','membership_change',c.lastrowid,after={'student_id':student_id,'effective_date':day,'slots':slot_ids},reason=reason)
            else:
                self._replace_memberships(c,student_id,slot_ids,a['_id'],reason)
                self.sync_semesters(c,strict_student=student_id)
            return {'student_id':student_id,'slot_ids':slot_ids,'effective_date':day}

    def _apply_due_memberships(self,c):
        if not installed(c): return
        for change in all_rows(c,"SELECT * FROM membership_change WHERE status='PENDING' AND effective_date<=%s ORDER BY effective_date,change_id",(self.clock().date(),)):
            student=one(c,'SELECT status FROM student WHERE student_id=%s',(change['student_id'],))
            if student['status']!='ACTIVE':
                c.execute("UPDATE membership_change SET status='CANCELLED' WHERE change_id=%s",(change['change_id'],)); continue
            self._membership_effective=datetime.combine(change['effective_date'],time())
            try: self._replace_memberships(c,change['student_id'],json.loads(change['slot_ids']),change['admin_id'],change['reason'])
            finally: del self._membership_effective
            c.execute("UPDATE membership_change SET status='APPLIED' WHERE change_id=%s",(change['change_id'],))

    def _sync_semester(self,c,semester_id):
        if not installed(c): return super()._sync_semester(c,semester_id)
        from .service import instant,minutes
        self._apply_due_memberships(c)
        term=one(c,'SELECT * FROM semester WHERE semester_id=%s',(semester_id,))
        self._snapshot_members(c,term)
        members=all_rows(c,"""SELECT m.*,t.business_id,t.schedule_kind,t.weekday,t.start_time,t.end_time,t.service_minutes,
            t.manager_admin_id,t.need_num,t.team_name FROM semester_member m JOIN service_slot t ON t.slot_id=m.slot_id
            WHERE m.semester_id=%s AND t.schedule_kind IN ('FIXED','WEEKLY')""",(semester_id,))
        off={(r['business_id'],r['week_no']) for r in all_rows(c,'SELECT * FROM business_week WHERE semester_id=%s AND working=0',(semester_id,))}
        desired={}; issues=set(); anchor=monday(term['start_date'])
        windows=all_rows(c,'SELECT * FROM business_window')
        for day in all_rows(c,'SELECT * FROM semester_day WHERE semester_id=%s',(semester_id,)):
            d=day['service_date']; week=(d-anchor).days//7+1
            if day['mode'] in ('MAKEUP_REQUIRED','UNCONFIRMED'): issues.add(f'{d}：{day["note"]}')
            for m in members:
                weekly=m['schedule_kind']=='WEEKLY'
                if (m['business_id'],week) in off: continue
                if weekly:
                    if d.isoweekday()!=7: continue
                    begins=datetime.combine(d,time(23,59,59))
                else:
                    if day['effective_weekday']!=m['weekday']: continue
                    begins=instant(d,m['start_time'])
                business_begins=datetime.combine(monday(d),time()) if weekly else begins
                if not any(w['business_id']==m['business_id'] and w['active_from']<=business_begins and (w['active_until'] is None or business_begins<w['active_until']) for w in windows):continue
                if begins<m['effective_from'] or m['effective_until'] is not None and begins>=m['effective_until']: continue
                if m['manager_admin_id'] is None or not weekly and m['need_num'] is None:
                    issues.add(f'{m["team_name"]}：负责人或容量待完善；已有固定队员照常排班计时')
                confirmed=not weekly or m['effective_from']<=datetime.combine(max(monday(d),term['start_date']),time())
                desired[m['student_id'],m['slot_id'],d]={**m,'week_no':week,'weekly_confirmed':confirmed}
        existing=all_rows(c,"""SELECT s.*,t.schedule_kind,t.business_id,t.start_time,t.end_time FROM schedule s
            JOIN service_slot t ON t.slot_id=s.slot_id WHERE (s.semester_id=%s OR s.schedule_date BETWEEN %s AND %s)
            AND t.schedule_kind IN ('FIXED','WEEKLY','LEGACY')""",(semester_id,term['start_date'],term['end_date']))
        live={}; blocked=set(); weekly_seen={}; created=cancelled=0
        for r in existing:
            key=r['student_id'],r['slot_id'],r['schedule_date']
            if r['status']=='CANCELLED':
                if r['cancel_reason'] in ('MANUAL','CREDIT','QUIT','WEEK_OFF','BUSINESS_ARCHIVED') or instant(r['schedule_date'],r['start_time'])<=self.clock(): blocked.add(key)
                continue
            if r['schedule_kind']=='WEEKLY': weekly_seen[r['student_id'],r['schedule_date']]=r
            if r['semester_id']==semester_id and key not in desired and r['status']=='ACTIVE' and (r['schedule_kind']=='WEEKLY' or instant(r['schedule_date'],r['start_time'])>self.clock()):
                c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='SYNC' WHERE schedule_id=%s",(r['schedule_id'],))
                c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')",(r['schedule_id'],))
                cancelled+=1
                if r['schedule_kind']=='WEEKLY': weekly_seen.pop((r['student_id'],r['schedule_date']),None)
            else: live[key]=r
        for key,m in sorted(desired.items()):
            sid,slot,d=key
            if key in live:
                if live[key]['semester_id'] is None: c.execute('UPDATE schedule SET semester_id=%s,week_no=%s WHERE schedule_id=%s',(semester_id,m['week_no'],live[key]['schedule_id']))
                continue
            if key in blocked or m['schedule_kind']=='WEEKLY' and (sid,d) in weekly_seen: continue
            if m['schedule_kind']=='FIXED' and any(r['student_id']==sid and r['schedule_date']==d and r['schedule_kind'] in ('FIXED','LEGACY') and minutes(r['start_time'])<minutes(m['end_time']) and minutes(m['start_time'])<minutes(r['end_time']) for r in live.values()):
                issues.add(f'{d}：{sid} 有时间冲突，请核对排班');continue
            c.execute('''INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date,semester_id,week_no,weekly_confirmed)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',(sid,slot,term['admin_id'],d,semester_id,m['week_no'],m['weekly_confirmed']))
            live[key]={**m,'student_id':sid,'schedule_date':d};created+=1
            if m['schedule_kind']=='WEEKLY': weekly_seen[sid,d]=live[key]
        c.execute('UPDATE semester SET issues=%s WHERE semester_id=%s',(json.dumps(sorted(issues),ensure_ascii=False),semester_id))
        return {'created':created,'cancelled':cancelled,'issues':sorted(issues)}

    def _settle_weeks(self,c):
        if not installed(c): return super()._settle_weeks(c)
        rows=all_rows(c,"""SELECT s.*,COALESCE(s.recognition_minutes,t.service_minutes) AS awarded,sem.admin_id AS owner
            FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id JOIN semester sem ON sem.semester_id=s.semester_id
            LEFT JOIN attendance a ON a.schedule_id=s.schedule_id
            WHERE s.status='ACTIVE' AND s.schedule_date<%s AND a.attendance_id IS NULL
            AND t.schedule_kind IN ('FIXED','WEEKLY') AND s.weekly_confirmed=1
            AND NOT EXISTS(SELECT 1 FROM business_week w WHERE w.business_id=t.business_id AND w.semester_id=s.semester_id AND w.week_no=s.week_no AND w.working=0)
            ORDER BY s.schedule_date,s.schedule_id""",(monday(self.clock().date()),))
        for r in rows:
            leave=one(c,"SELECT 1 FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'",(r['schedule_id'],))
            self._recognize(c,r['schedule_id'],r['owner'],0 if leave else r['awarded'],'AUTO_WEEKLY','LEAVE' if leave else 'NORMAL')
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status='PENDING'",(r['schedule_id'],))
        for term in {r['semester_id'] for r in rows}:
            subset=[r for r in rows if r['semester_id']==term]
            c.execute('UPDATE semester SET last_settled_at=%s WHERE semester_id=%s',(self.clock(),term))
            self.audit(c,subset[0]['owner'],'AUTO_WEEKLY_SETTLEMENT','semester',term,after={'settled':len(subset)},reason='系统按周自动结算')
        return {'settled':len(rows)}

    def _recognize(self,c,schedule_id,admin_id,duration,source,status='NORMAL'):
        c.execute('INSERT INTO attendance(schedule_id,admin_id,attendance_status,check_time,source) VALUES(%s,%s,%s,%s,%s)',(schedule_id,admin_id,status,self.clock(),source))
        aid=c.lastrowid
        if status in ('NORMAL','LATE'):
            c.execute('INSERT INTO service_record(attendance_id,service_minutes) VALUES(%s,%s)',(aid,duration))
        c.execute("UPDATE schedule SET status='COMPLETED' WHERE schedule_id=%s",(schedule_id,))
        return aid

    def confirm_garden(self,actor,schedule_id,reason):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('NORMAL','SUPER'));r=self.schedule(c,schedule_id);self.scope(a,r)
            require(r['schedule_kind']=='WEEKLY','仅适用于开心花园',422)
            require(monday(r['schedule_date'])<=self.clock().date(),'不能提前确认未来周服务',422)
            if r['status']=='COMPLETED': return {'replayed':True}
            require(r['status']=='ACTIVE','排班已取消')
            require(not one(c,'SELECT 1 FROM business_week WHERE business_id=%s AND semester_id=%s AND week_no=%s AND working=0',(r['business_id'],r['semester_id'],r['week_no'])),'本周停工')
            leave=one(c,"SELECT 1 FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'",(schedule_id,))
            require(not leave,'本周请假已批准，不能确认出勤')
            c.execute('UPDATE schedule SET weekly_confirmed=1 WHERE schedule_id=%s',(schedule_id,))
            self._recognize(c,schedule_id,a['_id'],90,'WEEKLY_CONFIRMED')
            self.audit(c,a['_id'],'CONFIRM_GARDEN','schedule',schedule_id,after={'service_minutes':90},reason=reason)
            return {'schedule_id':schedule_id,'service_minutes':90}

    def hours(self,actor,student_id=None,start=None,end=None,business_id=None,group_id=None):
        result=self._legacy_hours(actor,student_id,start,end)
        with self.db.transaction() as c:
            if not installed(c): return result
            lookup={r['slot_id']:r for r in all_rows(c,'SELECT t.slot_id,t.team_name,t.business_id,t.schedule_kind,b.name AS business_name FROM service_slot t JOIN business b ON b.business_id=t.business_id')}
            group_lookup={r['schedule_id']:r for r in all_rows(c,'SELECT s.schedule_id,s.group_id,g.name AS group_name FROM schedule s LEFT JOIN business_group g ON g.group_id=s.group_id')}
            steps={r['schedule_id']:r['minute_step'] for r in all_rows(c,'SELECT s.schedule_id,h.minute_step FROM hour_submission s JOIN collection_item i ON i.item_id=s.item_id JOIN hour_collection h ON h.collection_id=i.collection_id WHERE s.schedule_id IS NOT NULL')}
        for r in result['records']:
            r.update(lookup[r['slot_id']]);r.update(group_lookup[r['schedule_id']])
            r['minute_step']=steps.get(r['schedule_id'],1)
        if business_id is not None: result['records']=[r for r in result['records'] if r['business_id']==business_id]
        if group_id is not None:result['records']=[r for r in result['records'] if (r['group_id'] or 0)==group_id]
        groups={};subgroups={}
        for r in result['records']:
            if r['record_status']=='VALID':
                g=groups.setdefault(r['business_id'],{'business_id':r['business_id'],'business_name':r['business_name'],'total_minutes':0})
                g['total_minutes']+=r['service_minutes']
                sg=subgroups.setdefault((r['business_id'],r['group_id']),{'business_id':r['business_id'],'business_name':r['business_name'],'group_id':r['group_id'],'group_name':r['group_name'] or '未分组','total_minutes':0})
                sg['total_minutes']+=r['service_minutes']
        result.update(total_minutes=sum(g['total_minutes'] for g in groups.values()),business_totals=list(groups.values()),group_totals=list(subgroups.values()))
        result['total_hours']=result['total_minutes']/60
        return result
