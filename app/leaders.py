"""Scoped consultation/art leaders. No implicit inheritance of SUPER authority."""
import json
from datetime import datetime, time
from .db import Database, one, all_rows


def installed(c):
    return bool(one(c, "SHOW TABLES LIKE 'leader_scope'"))


def migrate(settings):
    with Database(settings).transaction() as c:
        ready = one(c, "SELECT 1 FROM feature_migration WHERE name='scoped_leaders_v1'")
    if not ready and settings.get('database') == 'volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        if not one(c, "SHOW COLUMNS FROM admin LIKE 'leader_student_id'"):
            c.execute("ALTER TABLE admin MODIFY role ENUM('NORMAL','SUPER','LEAD') NOT NULL DEFAULT 'NORMAL', ADD leader_student_id VARCHAR(32) NULL, ADD UNIQUE KEY uq_leader_student(leader_student_id), ADD FOREIGN KEY(leader_student_id) REFERENCES student(student_id)")
        c.execute('''CREATE TABLE IF NOT EXISTS leader_scope (
            scope_id INT PRIMARY KEY, name VARCHAR(80) NOT NULL, business_code VARCHAR(20) NOT NULL,
            weekday TINYINT NULL, admin_id BIGINT UNSIGNED NULL, assigned_at DATETIME NULL,
            FOREIGN KEY(admin_id) REFERENCES admin(admin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        for day in range(1, 8):
            c.execute("INSERT IGNORE INTO leader_scope(scope_id,name,business_code,weekday) VALUES(%s,%s,'CONSULT',%s)",
                      (day, '咨询服务'+'一二三四五六七'[day-1]+'分队', day))
        c.execute("INSERT IGNORE INTO leader_scope(scope_id,name,business_code) VALUES(8,'美育','ART')")
        c.execute('''CREATE TABLE IF NOT EXISTS leader_daily_report (
            report_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, scope_id INT NOT NULL,
            service_date DATE NOT NULL, payload LONGTEXT NOT NULL, created_at DATETIME NOT NULL,
            UNIQUE KEY uq_leader_report(scope_id,service_date), FOREIGN KEY(scope_id) REFERENCES leader_scope(scope_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawal_leader_review (
            withdrawal_id BIGINT UNSIGNED PRIMARY KEY, scope_id INT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'PENDING', admin_id BIGINT UNSIGNED NULL,
            reason VARCHAR(500) NOT NULL DEFAULT '', reviewed_at DATETIME NULL,
            FOREIGN KEY(withdrawal_id) REFERENCES withdrawal_application(withdrawal_id),
            FOREIGN KEY(scope_id) REFERENCES leader_scope(scope_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        # Existing applications keep their original final-review route.
        _migrate_business_scopes(c)
        c.execute("INSERT IGNORE INTO feature_migration(name,completed_at) VALUES('scoped_leaders_v1',NOW())")


def _migrate_business_scopes(c):
    """把「分队负责人」从按业务代码硬编码扩成 业务 × 星期 一张表。

    旧实现只给咨询服务 7 个分队、美育 1 个整业务范围；这里补上 business_id，
    为每个固定业务的每个星期生成一条范围行，美育的整业务范围拆成 7 条并停用旧行。
    旧的 scope_id 不删除：历史日报与退队初审仍挂在它上面。
    """
    marker = 'business_scopes_v1'
    if one(c, 'SELECT 1 FROM feature_migration WHERE name=%s', (marker,)):
        return
    if not one(c, "SHOW TABLES LIKE 'business'"):
        return
    if not one(c, "SHOW COLUMNS FROM leader_scope LIKE 'business_id'"):
        c.execute('ALTER TABLE leader_scope ADD business_id BIGINT UNSIGNED NULL, ADD active TINYINT NOT NULL DEFAULT 1')
    c.execute("SHOW INDEX FROM leader_scope WHERE Key_name='uq_business_scope'")
    if not c.fetchone():
        c.execute('ALTER TABLE leader_scope ADD UNIQUE KEY uq_business_scope(business_id,weekday)')
    c.execute("SHOW COLUMNS FROM leader_scope LIKE 'scope_id'")
    column = c.fetchone()
    # scope_id 被日报/退队初审外键引用，MySQL 不允许改成 AUTO_INCREMENT；新范围显式取 max+1。
    if not column:
        return
    c.execute('''UPDATE leader_scope g JOIN business b ON b.code=g.business_code
        SET g.business_id=b.business_id WHERE g.business_id IS NULL''')
    # 整业务的旧范围（美育）：负责人复制到该业务每个星期，旧行停用以避免重复日报。
    legacy = all_rows(c, 'SELECT * FROM leader_scope WHERE weekday IS NULL AND business_id IS NOT NULL AND active=1')
    for row in legacy:
        biz = one(c, 'SELECT * FROM business WHERE business_id=%s', (row['business_id'],))
        for day in range(1, 8):
            if not one(c, 'SELECT 1 FROM leader_scope WHERE business_id=%s AND weekday=%s', (row['business_id'], day)):
                c.execute('''INSERT INTO leader_scope(scope_id,name,business_id,business_code,weekday,admin_id,assigned_at,active)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,1)''',
                          (_next_scope(c), f"{biz['name']}周{'一二三四五六日'[day-1]}分队", row['business_id'],
                           row['business_code'], day, row['admin_id'], row['assigned_at']))
        c.execute('UPDATE leader_scope SET active=0 WHERE scope_id=%s', (row['scope_id'],))
    # 任意固定业务，每个星期都能有分队负责人
    for biz in all_rows(c, "SELECT * FROM business WHERE kind='FIXED' AND status='ACTIVE'"):
        for day in range(1, 8):
            if not one(c, 'SELECT 1 FROM leader_scope WHERE business_id=%s AND weekday=%s', (biz['business_id'], day)):
                c.execute('INSERT INTO leader_scope(scope_id,name,business_id,business_code,weekday,active) VALUES(%s,%s,%s,%s,%s,1)',
                          (_next_scope(c), f"{biz['name']}周{'一二三四五六日'[day-1]}分队", biz['business_id'], biz['code'], day))
    c.execute('INSERT IGNORE INTO feature_migration(name,completed_at) VALUES(%s,NOW())', (marker,))


def _next_scope(c):
    row = one(c, 'SELECT COALESCE(MAX(scope_id),0)+1 AS next_id FROM leader_scope')
    return int(row['next_id'])


class LeaderService:
    def leader_slots(self, c, admin_id):
        return all_rows(c, '''SELECT t.*,b.name AS business_name,b.code AS business_code FROM service_slot t
            JOIN business b ON b.business_id=t.business_id
            JOIN leader_scope g ON g.business_id=b.business_id AND g.weekday=t.weekday AND g.active=1
            WHERE g.admin_id=%s''', (admin_id,))

    def fixed_hour_recipients(self, c, slot_id):
        if not installed(c): return self._super_recipients(c)
        rows = all_rows(c, '''SELECT ad.admin_id FROM service_slot t JOIN business b ON b.business_id=t.business_id
            JOIN leader_scope g ON g.business_id=b.business_id AND g.weekday=t.weekday AND g.active=1
            JOIN admin ad ON ad.admin_id=g.admin_id LEFT JOIN student st ON st.student_id=ad.leader_student_id
            WHERE t.slot_id=%s AND ad.status='ACTIVE' AND (st.student_id IS NULL OR st.status='ACTIVE')''', (slot_id,))
        return [('admin', r['admin_id']) for r in rows] or self._super_recipients(c)

    def leader_membership_guard(self, c, a, student_id):
        from .service import require
        ids = a.get('_lead_slots', [])
        require(ids and one(c, 'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id IN ('+','.join(['%s']*len(ids))+')', [student_id]+ids),
                '该队员不属于你的管辖范围', 403)
        require(not one(c, "SELECT 1 FROM admin WHERE (student_id=%s OR leader_student_id=%s) AND role IN ('SUPER','LEAD')", (student_id,student_id)),
                '管理负责人的关联账号密码仅全局超级管理员可重置', 403)

    def leader_directory(self, actor):
        with self.db.transaction() as c:
            self.actor(c, actor, ('SUPER',))
            return all_rows(c, '''SELECT g.*,a.name AS admin_name,a.account,a.leader_student_id AS student_id,b.name AS business_name
                FROM leader_scope g LEFT JOIN admin a ON a.admin_id=g.admin_id LEFT JOIN business b ON b.business_id=g.business_id
                ORDER BY g.business_id,g.weekday,g.scope_id''')

    def _appoint_scope(self, c, actor_id, scope, student_id, reason):
        """把一个管理范围指派给某个在队队员；student_id 为空表示撤销。"""
        from .service import require
        aid = None; account = None
        if student_id:
            st = one(c, "SELECT * FROM student WHERE student_id=%s AND status='ACTIVE'", (student_id,))
            require(st, '请选择正常在队队员', 422)
            ad = one(c, 'SELECT * FROM admin WHERE leader_student_id=%s', (student_id,))
            if ad:
                aid, account = ad['admin_id'], ad['account']
                c.execute("UPDATE admin SET status='ACTIVE' WHERE admin_id=%s", (aid,))
            else:
                account = 'lead-'+student_id
                require(not one(c, 'SELECT 1 FROM admin WHERE account=%s', (account,)), '负责人账号已占用，请先核对账号', 409)
                c.execute("INSERT INTO admin(name,account,password_hash,role,leader_student_id) VALUES(%s,%s,%s,'LEAD',%s)",
                          (st['name'], account, st['password_hash'], student_id))
                aid = c.lastrowid
        if scope['admin_id'] == aid:
            return {'account': account, 'scope_id': scope['scope_id'], 'replayed': True}
        c.execute('UPDATE leader_scope SET admin_id=%s,assigned_at=%s WHERE scope_id=%s', (aid, self.clock(), scope['scope_id']))
        self.audit(c, actor_id, 'APPOINT_LEADER', 'leader_scope', scope['scope_id'],
                   {'admin_id': scope['admin_id']}, {'admin_id': aid, 'student_id': student_id}, reason)
        if aid:
            self._notice(c, [('admin', aid)], f'leader-assigned:{scope["scope_id"]}:{self.clock().isoformat()}', 'ACCOUNT',
                         '负责人管理范围已更新', scope['name']+'已授权给你。请使用负责人账号登录。', 'lead-workspace', scope['scope_id'])
        return {'account': account, 'scope_id': scope['scope_id'], 'password_hint': '使用该队员当前的志愿者密码'}

    def appoint_leader(self, actor, scope_id, student_id, reason):
        from .service import require, reason_text
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            scope = one(c, 'SELECT * FROM leader_scope WHERE scope_id=%s FOR UPDATE', (scope_id,))
            require(scope, '管理范围不存在', 404)
            require(int(scope.get('active', 1)) == 1, '该管理范围已停用，请改用按星期设置的分队范围', 422)
            return self._appoint_scope(c, a['_id'], scope, student_id, reason)

    def appoint_business_leader(self, actor, business_id, weekday, student_id, reason):
        """业务管理页直接用「业务 + 星期」任命分队负责人；业务负责人对本业务有此人事权。"""
        from .service import require, reason_text, require_business_owner
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER', 'NORMAL'))
            require(1 <= int(weekday) <= 7, '星期无效', 422)
            require_business_owner(c, a, business_id, '只能为本业务设置分队负责人')
            biz = one(c, 'SELECT * FROM business WHERE business_id=%s', (business_id,))
            require(biz, '业务不存在', 404)
            require(biz['status'] == 'ACTIVE', '仅启用中的业务可设置分队负责人', 422)
            scope = one(c, '''SELECT * FROM leader_scope WHERE business_id=%s AND weekday=%s AND active=1 FOR UPDATE''',
                        (business_id, int(weekday)))
            require(scope, '该业务该星期还没有分队负责人范围', 404)
            return self._appoint_scope(c, a['_id'], scope, student_id, reason)

    def _withdrawal_leader_scope(self, c, student_id):
        rows = all_rows(c, '''SELECT DISTINCT g.scope_id FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id
            JOIN business b ON b.business_id=t.business_id
            JOIN leader_scope g ON g.business_id=b.business_id AND g.weekday=t.weekday AND g.active=1
            WHERE m.student_id=%s ORDER BY g.scope_id''', (student_id,))
        # User-approved compatibility: ambiguous legacy memberships go directly
        # to global SUPER until the roster has been reconciled; never guess a team.
        return rows[0]['scope_id'] if len(rows)==1 else None

    def snapshot_withdrawal_leader(self,c,withdrawal_id,student_id):
        if not installed(c):return
        scope_id=self._withdrawal_leader_scope(c,student_id)
        c.execute('INSERT INTO withdrawal_leader_review(withdrawal_id,scope_id,status) VALUES(%s,%s,%s)',
                  (withdrawal_id,scope_id,'PENDING' if scope_id else 'NOT_REQUIRED'))

    def first_review_withdrawal(self,actor,withdrawal_id,approved,reason):
        from .service import require, reason_text
        reason=reason_text(reason)
        with self.db.transaction(True) as c:
            a=self.actor(c,actor,('LEAD',))
            r=one(c,'''SELECT p.student_id,p.approve_status,w.* FROM withdrawal_application p
                JOIN withdrawal_leader_review w ON w.withdrawal_id=p.withdrawal_id
                JOIN leader_scope g ON g.scope_id=w.scope_id WHERE p.withdrawal_id=%s AND g.admin_id=%s FOR UPDATE''',(withdrawal_id,a['_id']))
            require(r,'退队申请不属于你的范围',403)
            desired='APPROVED' if approved else 'REJECTED'
            if r['status']==desired and r['admin_id']==a['_id']:return {'status':desired,'replayed':True}
            require(r['approve_status']=='PENDING' and r['status']=='PENDING','申请已经处理，请刷新')
            c.execute('UPDATE withdrawal_leader_review SET status=%s,admin_id=%s,reason=%s,reviewed_at=%s WHERE withdrawal_id=%s',
                      (desired,a['_id'],reason,self.clock(),withdrawal_id))
            if not approved:
                c.execute("UPDATE withdrawal_application SET approve_status='REJECTED',admin_id=%s,approve_time=%s WHERE withdrawal_id=%s",(a['_id'],self.clock(),withdrawal_id))
            lid=self.audit(c,a['_id'],'WITHDRAWAL_FIRST','withdrawal_application',withdrawal_id,
                           {'student_id':r['student_id']},{'status':desired},reason)
            self._notice(c,[('student',r['student_id'])],f'withdrawal-first:{lid}','APPLICATION',
                         '退队初审'+('通过，等待全局超管终审' if approved else '未通过'),reason,'applications:withdrawal',withdrawal_id)
            if approved:self._notice(c,self._super_recipients(c),f'withdrawal-first:{lid}','APPLICATION','退队申请待终审',
                                     f"学号 {r['student_id']} 已通过负责人初审。",'applications:withdrawal',withdrawal_id)
            return {'status':desired}

    def guard_withdrawal_final(self,c,withdrawal_id):
        from .service import require
        if not installed(c):return
        r=one(c,'''SELECT w.*,g.admin_id AS leader_id,ad.status AS leader_status,st.status AS student_status
            FROM withdrawal_leader_review w LEFT JOIN leader_scope g ON g.scope_id=w.scope_id
            LEFT JOIN admin ad ON ad.admin_id=g.admin_id LEFT JOIN student st ON st.student_id=ad.leader_student_id
            WHERE w.withdrawal_id=%s''',(withdrawal_id,))
        # Missing/unavailable leaders must not strand whole-team withdrawal applications.
        if r and r['scope_id'] and r['leader_id'] and r['leader_status']=='ACTIVE' and r['student_status']=='ACTIVE':
            require(r['status']=='APPROVED','须先通过分队／美育负责人初审')

    def leader_workspace(self,actor):
        """Dedicated projection: never return a member's other-business records."""
        with self.db.transaction() as c:
            a=self.actor(c,actor,('LEAD',))
            slots=list(self.leader_slots(c,a['_id']));ids=[r['slot_id'] for r in slots]
            scopes=all_rows(c,'SELECT scope_id,name FROM leader_scope WHERE admin_id=%s AND active=1',(a['_id'],))
            result={'scopes':scopes,'slots':slots,'students':[],'schedules':[],'records':[],'admins':[],
                    'withdrawal':[],'reports':[],'logs':[],'semesters':[]}
            if not ids:return result
            marks=','.join(['%s']*len(ids))
            members=all_rows(c,f'''SELECT m.student_id,m.slot_id,t.team_name FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id WHERE m.slot_id IN ({marks})''',ids)
            result['students']=all_rows(c,f'''SELECT DISTINCT st.student_id,st.name,st.college,st.status FROM student st
                WHERE EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=st.student_id AND m.slot_id IN ({marks}))
                OR EXISTS(SELECT 1 FROM schedule s WHERE s.student_id=st.student_id AND s.slot_id IN ({marks})) ORDER BY st.student_id''',ids+ids)
            for st in result['students']:
                st['slots']=[{'slot_id':m['slot_id'],'name':m['team_name']} for m in members if m['student_id']==st['student_id']]
                st['can_reset']=bool(st['slots']) and not bool(one(c,"SELECT 1 FROM admin WHERE (student_id=%s OR leader_student_id=%s) AND role IN ('SUPER','LEAD')",(st['student_id'],st['student_id'])))
            result['schedules']=all_rows(c,f'''SELECT s.*,st.name AS student_name,t.team_name,t.period_no,t.start_time,t.end_time,t.location,
                t.manager_admin_id,t.schedule_kind,at.attendance_status,at.revision AS attendance_revision,at.source AS attendance_source,
                COALESCE(r.service_minutes,s.recognition_minutes,t.service_minutes) AS current_minutes,
                EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') AS leave_approved
                FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id JOIN student st ON st.student_id=s.student_id
                LEFT JOIN attendance at ON at.schedule_id=s.schedule_id LEFT JOIN service_record r ON r.attendance_id=at.attendance_id AND r.record_status='VALID'
                WHERE s.slot_id IN ({marks}) ORDER BY s.schedule_date DESC,s.schedule_id''',ids)
            result['records']=all_rows(c,f'''SELECT r.record_id,r.service_minutes,r.record_status,s.schedule_date,s.slot_id,s.student_id,st.name AS student_name,t.team_name
                FROM service_record r JOIN attendance at ON at.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=at.schedule_id
                JOIN student st ON st.student_id=s.student_id JOIN service_slot t ON t.slot_id=s.slot_id WHERE s.slot_id IN ({marks}) ORDER BY s.schedule_date DESC''',ids)
            # Names/IDs only: leaders may select active ordinary admins, never reset their independent accounts.
            result['admins']=all_rows(c,f'''SELECT ad.admin_id,ad.name,ad.role,ad.status FROM admin ad WHERE ad.role='NORMAL' AND ad.status='ACTIVE'
                AND (EXISTS(SELECT 1 FROM service_slot t WHERE t.manager_admin_id=ad.admin_id AND t.slot_id IN ({marks}))
                OR EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=ad.student_id AND m.slot_id IN ({marks})))''',ids*2)
            result['withdrawal']=all_rows(c,'''SELECT p.*,w.status AS first_status,w.reason AS first_reason FROM withdrawal_application p
                JOIN withdrawal_leader_review w ON w.withdrawal_id=p.withdrawal_id JOIN leader_scope g ON g.scope_id=w.scope_id WHERE g.admin_id=%s ORDER BY p.withdrawal_id DESC''',(a['_id'],))
            result['reports']=all_rows(c,'''SELECT r.report_id,r.service_date,g.name,r.created_at FROM leader_daily_report r JOIN leader_scope g ON g.scope_id=r.scope_id WHERE g.admin_id=%s ORDER BY r.service_date DESC LIMIT 100''',(a['_id'],))
            result['semesters']=all_rows(c,'SELECT semester_id,name,start_date,end_date,end_week FROM semester ORDER BY start_date DESC')
            # Strict target allowlist; omit raw JSON snapshots containing other-business IDs.
            result['logs']=all_rows(c,f'''SELECT l.log_id,l.operation_type,l.operation_time,l.reason,l.target_table,l.target_id,ad.name AS operator_name
                FROM operation_log l JOIN admin ad ON ad.admin_id=l.admin_id WHERE
                (l.target_table='service_slot' AND l.target_id IN ({marks})) OR
                (l.target_table='schedule' AND EXISTS(SELECT 1 FROM schedule s WHERE s.schedule_id=l.target_id AND s.slot_id IN ({marks}))) OR
                (l.target_table='attendance' AND EXISTS(SELECT 1 FROM attendance at JOIN schedule s ON s.schedule_id=at.schedule_id WHERE at.attendance_id=l.target_id AND s.slot_id IN ({marks}))) OR
                (l.target_table='service_record' AND EXISTS(SELECT 1 FROM service_record r JOIN attendance at ON at.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=at.schedule_id WHERE r.record_id=l.target_id AND s.slot_id IN ({marks})))
                OR (l.operation_type='RESET_PASSWORD' AND l.target_table='student' AND EXISTS(SELECT 1 FROM slot_member m WHERE m.student_id=l.target_id AND m.slot_id IN ({marks})))
                OR (l.operation_type='WITHDRAWAL_FIRST' AND l.target_table='withdrawal_application' AND EXISTS(SELECT 1 FROM withdrawal_leader_review w JOIN leader_scope g ON g.scope_id=w.scope_id WHERE w.withdrawal_id=l.target_id AND g.admin_id=%s))
                ORDER BY l.log_id DESC LIMIT 200''',ids*5+[a['_id']])
            return result

    def leader_report(self,actor,report_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('LEAD',))
            r=one(c,'''SELECT r.*,g.name FROM leader_daily_report r JOIN leader_scope g ON g.scope_id=r.scope_id
                WHERE r.report_id=%s AND g.admin_id=%s''',(report_id,a['_id']))
            require(r,'日报不存在或不属于你的范围',404)
            r['payload']=json.loads(r['payload']);return r

    def run_leader_reports(self):
        from .service import instant
        with self.db.transaction(True) as c:
            if not installed(c):return {'created':0}
            count=0
            scopes=all_rows(c,'''SELECT g.* FROM leader_scope g JOIN admin a ON a.admin_id=g.admin_id
                JOIN student st ON st.student_id=a.leader_student_id
                WHERE a.status='ACTIVE' AND st.status='ACTIVE' AND g.active=1 AND g.weekday IS NOT NULL ''')
            for scope in scopes:
                ids=[r['slot_id'] for r in all_rows(c,'''SELECT t.slot_id FROM service_slot t
                    WHERE t.business_id=%s AND t.weekday=%s AND t.status='ACTIVE' ''',(scope['business_id'],scope['weekday']))]
                if not ids:continue
                marks=','.join(['%s']*len(ids))
                days=all_rows(c,f'''SELECT s.schedule_date,MAX(t.end_time) AS ends FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
                    WHERE s.slot_id IN ({marks}) AND s.status<>'CANCELLED' AND s.schedule_date BETWEEN %s AND %s
                    AND NOT EXISTS(SELECT 1 FROM leader_daily_report r WHERE r.scope_id=%s AND r.service_date=s.schedule_date)
                    GROUP BY s.schedule_date ORDER BY s.schedule_date''',ids+[scope['assigned_at'].date(),self.clock().date(),scope['scope_id']])
                for day in days:
                    d=day['schedule_date']
                    if instant(d,day['ends'])>self.clock():continue
                    rows=all_rows(c,f'''SELECT s.student_id,st.name,t.team_name,s.status,
                        CASE WHEN a.attendance_status IS NULL AND EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') THEN 'LEAVE' ELSE a.attendance_status END AS attendance_status,
                        CASE WHEN s.status='CANCELLED' OR a.attendance_status IN ('ABSENT','LEAVE') OR EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') THEN 0 ELSE COALESCE(r.service_minutes,s.recognition_minutes,t.service_minutes) END AS expected_minutes,
                        CASE WHEN r.record_status='VALID' THEN r.service_minutes ELSE 0 END AS recognized_minutes
                        FROM schedule s JOIN student st ON st.student_id=s.student_id JOIN service_slot t ON t.slot_id=s.slot_id
                        LEFT JOIN attendance a ON a.schedule_id=s.schedule_id LEFT JOIN service_record r ON r.attendance_id=a.attendance_id
                        WHERE s.slot_id IN ({marks}) AND s.schedule_date=%s ORDER BY t.period_no,s.student_id''',ids+[d])
                    totals={r['student_id']:int(r['n']) for r in all_rows(c,f'''SELECT s.student_id,SUM(r.service_minutes) AS n
                        FROM service_record r JOIN attendance a ON a.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=a.schedule_id
                        WHERE r.record_status='VALID' AND s.slot_id IN ({marks}) AND s.schedule_date<=%s GROUP BY s.student_id''',ids+[d])}
                    for row in rows:row['cumulative_minutes']=totals.get(row['student_id'],0)
                    payload={'rows':rows,'expected_minutes':sum(r['expected_minutes'] for r in rows),'recognized_minutes':sum(r['recognized_minutes'] for r in rows)}
                    c.execute('INSERT INTO leader_daily_report(scope_id,service_date,payload,created_at) VALUES(%s,%s,%s,%s)',
                              (scope['scope_id'],d,json.dumps(payload,ensure_ascii=False,default=str),self.clock()))
                    rid=c.lastrowid;count+=1
                    self._notice(c,[('admin',scope['admin_id'])],f'leader-report:{rid}','SERVICE',f"{scope['name']} {d} 工作日报",
                                 f"{len(rows)} 条排班；预计 {payload['expected_minutes']} 分钟，已认定 {payload['recognized_minutes']} 分钟。日报为生成时快照，未登记考勤按默认出勤预计，正式时长仍按周结算。",
                                 'lead-workspace',rid)
            return {'created':count}
