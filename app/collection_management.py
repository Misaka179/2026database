"""Business-scoped collection administrators and collection lifecycle."""
from .db import one,all_rows
from .directory import DirectoryManagement
from .collection_governance_schema import installed


class CollectionManagement(DirectoryManagement):
    def _collection_admins(self,c,business_id,group_id=None):
        return list(all_rows(c,"""SELECT a.admin_id,a.name FROM admin a LEFT JOIN student s ON s.student_id=a.student_id
            WHERE a.role='NORMAL' AND a.status='ACTIVE' AND (a.student_id IS NULL OR s.status='ACTIVE')
            AND (EXISTS(SELECT 1 FROM collection_manager m WHERE m.admin_id=a.admin_id AND m.business_id=%s)
            OR EXISTS(SELECT 1 FROM collection_group_manager m WHERE m.admin_id=a.admin_id AND m.group_id=%s)) ORDER BY a.admin_id""",(business_id,group_id)))

    def _collection_scope(self,c,a,business_id,group_id=None):
        from .service import require
        if a['_role']=='SUPER':return
        require(a['_role']=='NORMAL' and (one(c,'SELECT 1 FROM collection_manager WHERE admin_id=%s AND business_id=%s',(a['_id'],business_id)) or group_id is not None and one(c,'SELECT 1 FROM collection_group_manager m JOIN business_group g ON g.group_id=m.group_id WHERE m.admin_id=%s AND m.group_id=%s AND g.business_id=%s',(a['_id'],group_id,business_id))),
                '没有该业务的时长征集管理权限',403)

    def _collection_business(self,c,business_id):
        from .service import require
        b=self._active_business(c,business_id)
        require(b and b['kind']=='EVENT','请选择非固定业务的时长征集管理范围',422)
        return b

    def collection_management(self,actor):
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'));own=a['_role']=='NORMAL'
            grants=all_rows(c,'''SELECT m.*,a.name AS admin_name,a.account,b.name AS business_name FROM collection_manager m
                JOIN admin a ON a.admin_id=m.admin_id JOIN business b ON b.business_id=m.business_id'''+(' WHERE m.admin_id=%s' if own else '')+' ORDER BY m.admin_id,m.business_id',(a['_id'],) if own else ())
            requests=all_rows(c,'''SELECT r.*,a.name AS admin_name,a.account,b.name AS business_name FROM collection_scope_request r
                JOIN admin a ON a.admin_id=r.admin_id JOIN business b ON b.business_id=r.business_id'''+(' WHERE r.admin_id=%s' if own else '')+' ORDER BY request_id DESC',(a['_id'],) if own else ())
            group_grants=all_rows(c,'''SELECT m.*,g.business_id,g.name AS group_name,a.name AS admin_name,a.account,b.name AS business_name
                FROM collection_group_manager m JOIN business_group g ON g.group_id=m.group_id JOIN business b ON b.business_id=g.business_id
                JOIN admin a ON a.admin_id=m.admin_id'''+(' WHERE m.admin_id=%s' if own else ''),(a['_id'],) if own else ())
            groups=all_rows(c,"SELECT g.*,b.name AS business_name FROM business_group g JOIN business b ON b.business_id=g.business_id WHERE b.status='ACTIVE'")
            names={g['group_id']:g['name'] for g in groups}
            for r in requests:r['group_name']=names.get(r['group_id'])
            return {'grants':grants,'group_grants':group_grants,'requests':requests,'groups':groups,'businesses':all_rows(c,"SELECT business_id,name FROM business WHERE kind='EVENT' AND status='ACTIVE' ORDER BY business_id")}

    def set_collection_managers(self,actor,admin_id,business_ids,reason,group_ids=None):
        from .service import require,reason_text
        reason=reason_text(reason);ids=sorted(set(business_ids))
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',))
            manager=one(c,"SELECT * FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'",(admin_id,))
            require(manager,'请选择有效普通管理员',422)
            self.actor(c,{'kind':'admin','id':admin_id},('NORMAL',))
            for bid in ids:self._collection_business(c,bid)
            previous_groups=[r['group_id'] for r in all_rows(c,'SELECT group_id FROM collection_group_manager WHERE admin_id=%s ORDER BY group_id',(admin_id,))]
            gids=previous_groups if group_ids is None else sorted(set(group_ids))
            for gid in gids:
                g=one(c,'SELECT * FROM business_group WHERE group_id=%s',(gid,));require(g,'小组不存在',422);self._collection_business(c,g['business_id'])
            previous=[r['business_id'] for r in all_rows(c,'SELECT business_id FROM collection_manager WHERE admin_id=%s ORDER BY business_id',(admin_id,))]
            if ids==previous and gids==previous_groups:return {'replayed':True,'business_ids':ids,'group_ids':gids}
            c.execute('DELETE FROM collection_manager WHERE admin_id=%s',(admin_id,))
            for bid in ids:c.execute('INSERT INTO collection_manager VALUES(%s,%s,%s,%s)',(admin_id,bid,a['_id'],self.clock()))
            c.execute('DELETE FROM collection_group_manager WHERE admin_id=%s',(admin_id,))
            for gid in gids:c.execute('INSERT INTO collection_group_manager VALUES(%s,%s,%s,%s)',(admin_id,gid,a['_id'],self.clock()))
            log_id=self.audit(c,a['_id'],'SET_COLLECTION_MANAGERS','admin',admin_id,{'business_ids':previous,'group_ids':previous_groups},{'business_ids':ids,'group_ids':gids},reason)
            self._notice(c,[('admin',admin_id)],f'collection-grant:{log_id}','SCOPE','时长征集管理范围已调整',reason,'collection-management',admin_id)
            return {'business_ids':ids,'group_ids':gids}

    def request_collection_scope(self,actor,business_ids,reason,group_ids=None):
        from .service import require,reason_text
        reason=reason_text(reason);ids=sorted(set(business_ids));gids=sorted(set(group_ids or []));require(ids or gids,'请至少选择一个业务或小组',422)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('NORMAL',));created=[]
            scopes=[(bid,None) for bid in ids]
            for gid in gids:
                g=one(c,'SELECT * FROM business_group WHERE group_id=%s',(gid,));require(g,'小组不存在',422);scopes.append((g['business_id'],gid))
            for bid,gid in scopes:
                b=self._collection_business(c,bid)
                require(not one(c,'SELECT 1 FROM collection_manager WHERE admin_id=%s AND business_id=%s',(a['_id'],bid)),'已经拥有所选业务权限',422)
                require(gid is None or not one(c,'SELECT 1 FROM collection_group_manager WHERE admin_id=%s AND group_id=%s',(a['_id'],gid)),'已经拥有小组权限',422)
                existing=one(c,"SELECT request_id FROM collection_scope_request WHERE admin_id=%s AND business_id=%s AND group_id <=> %s AND status='PENDING'",(a['_id'],bid,gid))
                if existing:created.append(existing['request_id']);continue
                c.execute('INSERT INTO collection_scope_request(admin_id,business_id,group_id,reason,created_at) VALUES(%s,%s,%s,%s,%s)',(a['_id'],bid,gid,reason,self.clock()))
                rid=c.lastrowid;created.append(rid)
                self.audit(c,a['_id'],'REQUEST_COLLECTION_SCOPE','collection_scope_request',rid,after={'business_id':bid},reason=reason)
                self._notice(c,self._super_recipients(c),f'collection-scope-request:{rid}','SCOPE','征集管理范围申请待审批',f"{a['name']} 申请管理 {b['name']}。",'collection-management',rid)
            return {'request_ids':created}

    def decide_collection_scope(self,actor,request_id,approved,expected_revision,reason=''):
        from .service import require,reason_text
        if not approved:reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER',));r=one(c,'SELECT * FROM collection_scope_request WHERE request_id=%s FOR UPDATE',(request_id,))
            require(r,'申请不存在',404);status='APPROVED' if approved else 'REJECTED'
            if r['status']==status and r['revision']==expected_revision+1:return {'replayed':True}
            require(r['status']=='PENDING' and r['revision']==expected_revision,'申请已处理，请刷新',409)
            if approved:
                self.actor(c,{'kind':'admin','id':r['admin_id']},('NORMAL',))
                self._active_business(c,r['business_id'])
                table='collection_group_manager' if r['group_id'] else 'collection_manager'
                c.execute(f'INSERT IGNORE INTO {table} VALUES(%s,%s,%s,%s)',(r['admin_id'],r['group_id'] or r['business_id'],a['_id'],self.clock()))
            c.execute('UPDATE collection_scope_request SET status=%s,review_reason=%s,review_admin_id=%s,reviewed_at=%s,revision=revision+1 WHERE request_id=%s',(status,reason,a['_id'],self.clock(),request_id))
            self.audit(c,a['_id'],'DECIDE_COLLECTION_SCOPE','collection_scope_request',request_id,r,{'status':status},reason)
            self._notice(c,[('admin',r['admin_id'])],f'collection-scope-decision:{request_id}','SCOPE','管理范围申请'+('已通过' if approved else '已打回'),reason or '权限已生效，可进入时长征集发起和初审。','collection-management',request_id)
            return {'status':status}

    def _collection_open(self,collection):
        return collection.get('status','OPEN')=='OPEN' and (not collection.get('submission_deadline') or self.clock().date()<=collection['submission_deadline'])

    def _close_collection(self,c,row,admin_id,reason):
        if row['status']=='CLOSED':return {'replayed':True,'status':'CLOSED'}
        c.execute("UPDATE hour_collection SET status='CLOSED',closed_at=%s,close_reason=%s WHERE collection_id=%s",(self.clock(),reason,row['collection_id']))
        recipients=[('student',p['student_id']) for p in all_rows(c,'SELECT student_id FROM collection_person WHERE collection_id=%s',(row['collection_id'],))]
        recipients+=self._super_recipients(c)+[('admin',m['admin_id']) for m in self._collection_admins(c,row['business_id'],row.get('group_id'))]
        self._notice(c,recipients,f"collection-closed:{row['collection_id']}",'COLLECTION','时长征集已结束',f"{row['title']}：{reason}。已提交的申报继续审批。",'collections',row['collection_id'])
        self.audit(c,admin_id,'CLOSE_COLLECTION','hour_collection',row['collection_id'],{'status':row['status']},{'status':'CLOSED'},reason)
        return {'status':'CLOSED'}

    def close_collection(self,actor,collection_id,reason):
        from .service import require,reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('SUPER','NORMAL'));row=one(c,'SELECT * FROM hour_collection WHERE collection_id=%s FOR UPDATE',(collection_id,))
            require(row,'征集不存在',404);self._collection_scope(c,a,row['business_id'],row.get('group_id'))
            return self._close_collection(c,row,a['_id'],reason)

    def run_collection_deadlines(self):
        with self.db.transaction(True) as c:
            if not installed(c):return {'closed':0}
            rows=all_rows(c,"SELECT * FROM hour_collection WHERE status='OPEN' AND submission_deadline<%s",(self.clock().date(),))
            for row in rows:self._close_collection(c,row,row['admin_id'],'申报截止日期已过，系统自动结束')
            return {'closed':len(rows)}
