"""Business-scoped collection administrators and collection lifecycle."""
from datetime import timedelta
from .db import one,all_rows
from .directory import DirectoryManagement
from .collection_governance_schema import installed


class CollectionManagement(DirectoryManagement):
    @staticmethod
    def _collection_weekdays(start_date,end_date):
        """征集服务日期覆盖的星期；缺日期返回 None，表示不加星期限制。"""
        if not start_date or not end_date:return None
        days=set();day=start_date
        while day<=end_date:
            days.add(day.isoweekday())
            if len(days)==7:break
            day+=timedelta(days=1)
        return days

    def _leader_weekdays(self,c,admin_id,business_id):
        """该管理员在该业务被任命的星期集合。"""
        return {int(r['weekday']) for r in all_rows(c,"""SELECT g.weekday FROM leader_scope g
            JOIN admin ad ON ad.admin_id=g.admin_id
            WHERE g.business_id=%s AND g.admin_id=%s AND g.active=1 AND g.weekday IS NOT NULL
            AND ad.role='NORMAL' AND ad.status='ACTIVE'""",(business_id,admin_id))}

    def _leader_businesses(self,c,admin_id):
        scopes={}
        for r in all_rows(c,"""SELECT g.business_id,g.weekday FROM leader_scope g
            JOIN admin ad ON ad.admin_id=g.admin_id JOIN business b ON b.business_id=g.business_id
            WHERE g.admin_id=%s AND g.active=1 AND g.weekday IS NOT NULL AND g.business_id IS NOT NULL
            AND ad.role='NORMAL' AND ad.status='ACTIVE' AND b.status='ACTIVE'""",(admin_id,)):
            scopes.setdefault(r['business_id'],set()).add(int(r['weekday']))
        return scopes

    def _is_collection_owner(self,c,a,business_id,start_date=None,end_date=None):
        """时长征集只归业务总负责人；分队负责人、时段负责人均不参与。"""
        if a['_role']=='SUPER':return True
        if a['_role']=='NORMAL':
            b=one(c,'SELECT total_manager_admin_id FROM business WHERE business_id=%s',(business_id,))
            return bool(b and b.get('total_manager_admin_id')==a['_id'])
        return False

    def _owned_business_ids(self,c,a):
        return sorted({r['business_id'] for r in all_rows(c,"""SELECT business_id FROM business
            WHERE status='ACTIVE' AND total_manager_admin_id=%s""",(a['_id'],))})

    def _collection_admins(self,c,business_id,group_id=None,start_date=None,end_date=None):
        """征集初审人：仅业务总负责人（管理员账号）。分队／时段负责人不参与征集。"""
        owners=all_rows(c,"""SELECT a.admin_id,a.name FROM admin a
            JOIN business b ON b.business_id=%s
            WHERE a.role='NORMAL' AND a.status='ACTIVE'
            AND a.admin_id=b.total_manager_admin_id""",(business_id,))
        return [{'admin_id':r['admin_id'],'name':r['name']} for r in owners]

    def _collection_scope(self,c,a,business_id,group_id=None,start_date=None,end_date=None):
        from .service import require
        if a['_role']=='SUPER':return
        require(self._is_collection_owner(c,a,business_id,start_date,end_date),'没有该业务的时长征集管理权限',403)

    def _collection_business(self,c,business_id):
        from .service import require
        b=self._active_business(c,business_id)
        require(b and b['kind']=='EVENT','请选择非固定业务的时长征集管理范围',422)
        return b

    def _collection_open(self,collection):
        return collection.get('status','OPEN')=='OPEN' and (not collection.get('submission_deadline') or self.clock().date()<=collection['submission_deadline'])

    def _close_collection(self,c,row,admin_id,reason):
        if row['status']=='CLOSED':return {'replayed':True,'status':'CLOSED'}
        c.execute("UPDATE hour_collection SET status='CLOSED',closed_at=%s,close_reason=%s WHERE collection_id=%s",(self.clock(),reason,row['collection_id']))
        recipients=[('student',p['student_id']) for p in all_rows(c,'SELECT student_id FROM collection_person WHERE collection_id=%s',(row['collection_id'],))]
        recipients+=self._super_recipients(c)+[('admin',m['admin_id']) for m in self._collection_admins(c,row['business_id'],row.get('group_id'),row['start_date'],row['end_date'])]
        reason_text=(reason or '').strip()
        message=f"{row['title']}：{reason_text}" if reason_text and not reason_text.isdigit() else row['title']
        self._notice(c,recipients,f"collection-closed:{row['collection_id']}",'COLLECTION','时长征集已结束',message,'collections',row['collection_id'])
        self.audit(c,admin_id,'CLOSE_COLLECTION','hour_collection',row['collection_id'],{'status':row['status']},{'status':'CLOSED'},reason)
        return {'status':'CLOSED'}

    def close_collection(self,actor,collection_id,reason):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'));row=one(c,'SELECT * FROM hour_collection WHERE collection_id=%s FOR UPDATE',(collection_id,))
            require(row,'征集不存在',404)
            self._collection_scope(c,a,row['business_id'],row.get('group_id'),row['start_date'],row['end_date'])
            return self._close_collection(c,row,a['_id'],reason)

    def run_collection_deadlines(self):
        with self.db.transaction(True) as c:
            if not installed(c):return {'closed':0}
            rows=all_rows(c,"SELECT * FROM hour_collection WHERE status='OPEN' AND submission_deadline<%s",(self.clock().date(),))
            for row in rows:self._close_collection(c,row,row['admin_id'],'申报截止日期已过，系统自动结束')
            return {'closed':len(rows)}
