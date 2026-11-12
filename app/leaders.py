"""Scope appointments on administrator accounts.

All scoped leaders are ordinary administrators (role NORMAL).  A volunteer
account and an administrator account are independent: appointments never
create accounts, never copy passwords and never write student_id.
"""
import json
from datetime import datetime, time
from .db import Database, one, all_rows


def installed(c):
    return bool(one(c, "SHOW TABLES LIKE 'leader_scope'"))


# ---------------------------------------------------------------------------
# One administrator, one active assignment
# ---------------------------------------------------------------------------

def assignment_conflicts(c, admin_id, except_table=None, except_id=None):
    """True when the administrator already holds an active scope elsewhere.

    The three appointment kinds are mutually exclusive:
      business.total_manager_admin_id, leader_scope.admin_id,
      service_slot.manager_admin_id.
    """
    if admin_id is None:
        return False
    if except_table == 'business':
        if one(c, 'SELECT 1 FROM business WHERE total_manager_admin_id=%s AND business_id<>%s',
               (admin_id, except_id)):
            return True
    elif one(c, 'SELECT 1 FROM business WHERE total_manager_admin_id=%s', (admin_id,)):
        return True
    if except_table == 'leader_scope':
        if one(c, 'SELECT 1 FROM leader_scope WHERE admin_id=%s AND active=1 AND scope_id<>%s',
               (admin_id, except_id)):
            return True
    elif one(c, 'SELECT 1 FROM leader_scope WHERE admin_id=%s AND active=1', (admin_id,)):
        return True
    if except_table == 'service_slot':
        if one(c, 'SELECT 1 FROM service_slot WHERE manager_admin_id=%s AND slot_id<>%s',
               (admin_id, except_id)):
            return True
    elif one(c, 'SELECT 1 FROM service_slot WHERE manager_admin_id=%s', (admin_id,)):
        return True
    return False


def require_appointable_admin(c, admin_id):
    from .service import require
    row = one(c, "SELECT * FROM admin WHERE admin_id=%s AND role='NORMAL' AND status='ACTIVE'", (admin_id,))
    require(row, '请选择启用的普通管理员账号', 422)
    return row


def require_no_other_assignment(c, admin_id, except_table=None, except_id=None, message='该管理员已有其他任命，一个账号只能负责一个范围'):
    from .service import require
    require(not assignment_conflicts(c, admin_id, except_table, except_id), message, 409)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(settings):
    with Database(settings).transaction() as c:
        ready = one(c, "SELECT 1 FROM feature_migration WHERE name='scoped_leaders_v1'")
    if not ready and settings.get('database') == 'volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS leader_scope (
            scope_id INT PRIMARY KEY, name VARCHAR(80) NOT NULL, business_id BIGINT UNSIGNED NULL,
            weekday TINYINT NULL, admin_id BIGINT UNSIGNED NULL, assigned_at DATETIME NULL,
            active TINYINT NOT NULL DEFAULT 1,
            FOREIGN KEY(admin_id) REFERENCES admin(admin_id),
            FOREIGN KEY(business_id) REFERENCES business(business_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')

        # Retire the old LEAD identity.  Existing LEAD accounts are disabled;
        # their scope rows are released so a SUPER can appoint a real
        # administrator account.  No password or student link is copied.
        role = one(c, "SHOW COLUMNS FROM admin LIKE 'role'")
        if role and 'LEAD' in (role.get('Type') or ''):
            c.execute("UPDATE admin SET status='DISABLED' WHERE role='LEAD'")
            c.execute('''UPDATE leader_scope g JOIN admin a ON a.admin_id=g.admin_id
                SET g.admin_id=NULL,g.assigned_at=NULL WHERE a.role='LEAD' ''')
            c.execute("UPDATE admin SET role='NORMAL' WHERE role='LEAD'")
            c.execute("ALTER TABLE admin MODIFY role ENUM('NORMAL','SUPER') NOT NULL DEFAULT 'NORMAL'")
        if one(c, "SHOW COLUMNS FROM admin LIKE 'student_id'"):
            c.execute('UPDATE admin SET student_id=NULL')

        for day in range(1, 8):
            c.execute("INSERT IGNORE INTO leader_scope(scope_id,name,business_id,weekday) VALUES(%s,%s,(SELECT business_id FROM business WHERE code='CONSULT'),%s)",
                      (day, '咨询服务'+'一二三四五六七'[day-1]+'分队', day))
        c.execute("INSERT IGNORE INTO leader_scope(scope_id,name,business_id) VALUES(8,'美育',(SELECT business_id FROM business WHERE code='ART'))")
        # One active scope per administrator; NULLs may repeat.
        c.execute("SHOW INDEX FROM leader_scope WHERE Key_name='uq_leader_admin'")
        if not c.fetchone():
            c.execute("ALTER TABLE leader_scope ADD UNIQUE KEY uq_leader_admin(admin_id)")
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
        _migrate_business_scopes(c)
        c.execute("INSERT IGNORE INTO feature_migration(name,completed_at) VALUES('scoped_leaders_v1',NOW())")
        _migrate_event_scopes(c)
        c.execute("INSERT IGNORE INTO feature_migration(name,completed_at) VALUES('scoped_leaders_v2',NOW())")


def ensure_event_scopes(c, business_id):
    """Non-fixed businesses also need one scope row per weekday."""
    if not installed(c):
        return
    biz = one(c, 'SELECT business_id,name FROM business WHERE business_id=%s', (business_id,))
    if not biz:
        return
    for day in range(1, 8):
        if not one(c, 'SELECT 1 FROM leader_scope WHERE business_id=%s AND weekday=%s', (business_id, day)):
            c.execute('''INSERT INTO leader_scope(scope_id,name,business_id,weekday,active)
                VALUES(%s,%s,%s,%s,1)''',
                      (_next_scope(c), f"{biz['name']}周{'一二三四五六日'[day-1]}分队", business_id, day))


def _migrate_event_scopes(c):
    marker = 'event_leader_scopes_v1'
    if one(c, 'SELECT 1 FROM feature_migration WHERE name=%s', (marker,)):
        return
    if not one(c, "SHOW TABLES LIKE 'business'") or not one(c, "SHOW TABLES LIKE 'leader_scope'"):
        return
    for biz in all_rows(c, "SELECT business_id FROM business WHERE kind='EVENT' AND status='ACTIVE'"):
        ensure_event_scopes(c, biz['business_id'])
    c.execute('INSERT IGNORE INTO feature_migration(name,completed_at) VALUES(%s,NOW())', (marker,))


def _migrate_business_scopes(c):
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
    if not column:
        return
    legacy = all_rows(c, 'SELECT * FROM leader_scope WHERE weekday IS NULL AND business_id IS NOT NULL AND active=1')
    for row in legacy:
        biz = one(c, 'SELECT * FROM business WHERE business_id=%s', (row['business_id'],))
        for day in range(1, 8):
            if not one(c, 'SELECT 1 FROM leader_scope WHERE business_id=%s AND weekday=%s', (row['business_id'], day)):
                c.execute('''INSERT INTO leader_scope(scope_id,name,business_id,weekday,admin_id,assigned_at,active)
                    VALUES(%s,%s,%s,%s,%s,%s,1)''',
                          (_next_scope(c), f"{biz['name']}周{'一二三四五六日'[day-1]}分队", row['business_id'],
                           day, row['admin_id'], row['assigned_at']))
        c.execute('UPDATE leader_scope SET active=0 WHERE scope_id=%s', (row['scope_id'],))
    for biz in all_rows(c, "SELECT * FROM business WHERE kind='FIXED' AND status='ACTIVE'"):
        for day in range(1, 8):
            if not one(c, 'SELECT 1 FROM leader_scope WHERE business_id=%s AND weekday=%s', (biz['business_id'], day)):
                c.execute('INSERT INTO leader_scope(scope_id,name,business_id,weekday,active) VALUES(%s,%s,%s,%s,1)',
                          (_next_scope(c), f"{biz['name']}周{'一二三四五六日'[day-1]}分队", biz['business_id'], day))
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
            JOIN admin ad ON ad.admin_id=g.admin_id
            WHERE t.slot_id=%s AND ad.status='ACTIVE' AND ad.role='NORMAL' ''', (slot_id,))
        return [('admin', r['admin_id']) for r in rows] or self._super_recipients(c)

    def leader_membership_guard(self, c, a, student_id):
        from .service import require
        ids = a.get('_lead_slots', [])
        require(ids and one(c, 'SELECT 1 FROM slot_member WHERE student_id=%s AND slot_id IN ('+','.join(['%s']*len(ids))+')', [student_id]+ids),
                '该队员不属于你的管辖范围', 403)

    def leader_directory(self, actor):
        with self.db.transaction() as c:
            self.actor(c, actor, ('SUPER',))
            return all_rows(c, '''SELECT g.*,a.name AS admin_name,a.account,b.name AS business_name
                FROM leader_scope g LEFT JOIN admin a ON a.admin_id=g.admin_id LEFT JOIN business b ON b.business_id=g.business_id
                ORDER BY g.business_id,g.weekday,g.scope_id''')

    def _appoint_scope(self, c, actor_id, scope, admin_id, reason):
        """Assign a scope to an existing administrator; None releases it."""
        from .service import require
        if admin_id is not None:
            require_appointable_admin(c, admin_id)
            require_no_other_assignment(c, admin_id, 'leader_scope', scope['scope_id'])
        if scope['admin_id'] == admin_id:
            return {'scope_id': scope['scope_id'], 'admin_id': admin_id, 'replayed': True}
        c.execute('UPDATE leader_scope SET admin_id=%s,assigned_at=%s WHERE scope_id=%s',
                  (admin_id, self.clock() if admin_id else None, scope['scope_id']))
        self.audit(c, actor_id, 'APPOINT_LEADER', 'leader_scope', scope['scope_id'],
                   {'admin_id': scope['admin_id']}, {'admin_id': admin_id}, reason)
        if admin_id:
            self._notice(c, [('admin', admin_id)], f'leader-assigned:{scope["scope_id"]}:{self.clock().isoformat()}', 'ACCOUNT',
                         '负责人管理范围已更新', scope['name']+'已授权给你。', 'businesses', scope['scope_id'])
        return {'scope_id': scope['scope_id'], 'admin_id': admin_id}

    def appoint_leader(self, actor, scope_id, admin_id, reason):
        from .service import require, reason_text
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            scope = one(c, 'SELECT * FROM leader_scope WHERE scope_id=%s FOR UPDATE', (scope_id,))
            require(scope, '管理范围不存在', 404)
            require(int(scope.get('active', 1)) == 1, '该管理范围已停用', 422)
            return self._appoint_scope(c, a['_id'], scope, admin_id, reason)

    def appoint_business_leader(self, actor, business_id, weekday, admin_id, reason):
        """Business owner (or SUPER) appoints the weekday leader from admin accounts."""
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
            return self._appoint_scope(c, a['_id'], scope, admin_id, reason)

    def _withdrawal_leader_scope(self, c, student_id):
        rows = all_rows(c, '''SELECT DISTINCT g.scope_id FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id
            JOIN business b ON b.business_id=t.business_id
            JOIN leader_scope g ON g.business_id=b.business_id AND g.weekday=t.weekday AND g.active=1
            WHERE m.student_id=%s ORDER BY g.scope_id''', (student_id,))
        return rows[0]['scope_id'] if len(rows)==1 else None

    def snapshot_withdrawal_leader(self,c,withdrawal_id,student_id):
        if not installed(c):return
        scope_id=self._withdrawal_leader_scope(c,student_id)
        c.execute('INSERT INTO withdrawal_leader_review(withdrawal_id,scope_id,status) VALUES(%s,%s,%s)',
                  (withdrawal_id,scope_id,'PENDING' if scope_id else 'NOT_REQUIRED'))

    def first_review_withdrawal(self,actor,withdrawal_id,approved,reason):
        # 兼容旧调用：退队只保留一次审核，负责人通过即为最终结果。
        return self.approve_withdrawal(actor,withdrawal_id,approved,reason)

    def leader_workspace(self,actor):
        """Scoped administrator view; never returns another business's data."""
        with self.db.transaction() as c:
            a=self.actor(c,actor,('NORMAL',))
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
                st['can_reset']=bool(st['slots'])
            result['schedules']=all_rows(c,f'''SELECT s.*,st.name AS student_name,t.team_name,t.period_no,t.start_time,t.end_time,
                t.manager_admin_id,t.schedule_kind,at.attendance_status,at.revision AS attendance_revision,at.source AS attendance_source,
                COALESCE(r.service_minutes,s.recognition_minutes,t.service_minutes) AS current_minutes,
                EXISTS(SELECT 1 FROM leave_application l WHERE l.schedule_id=s.schedule_id AND l.approve_status='APPROVED') AS leave_approved
                FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id JOIN student st ON st.student_id=s.student_id
                LEFT JOIN attendance at ON at.schedule_id=s.schedule_id LEFT JOIN service_record r ON r.attendance_id=at.attendance_id AND r.record_status='VALID'
                WHERE s.slot_id IN ({marks}) ORDER BY s.schedule_date DESC,s.schedule_id''',ids)
            result['records']=all_rows(c,f'''SELECT r.record_id,r.service_minutes,r.record_status,s.schedule_date,s.slot_id,s.student_id,st.name AS student_name,t.team_name
                FROM service_record r JOIN attendance at ON at.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=at.schedule_id
                JOIN student st ON st.student_id=s.student_id JOIN service_slot t ON t.slot_id=s.slot_id WHERE s.slot_id IN ({marks}) ORDER BY s.schedule_date DESC''',ids)
            result['admins']=all_rows(c,"SELECT admin_id,name,role,status FROM admin WHERE role='NORMAL' AND status='ACTIVE'")
            result['withdrawal']=all_rows(c,'''SELECT p.*,w.status AS first_status,w.reason AS first_reason FROM withdrawal_application p
                JOIN withdrawal_leader_review w ON w.withdrawal_id=p.withdrawal_id JOIN leader_scope g ON g.scope_id=w.scope_id WHERE g.admin_id=%s ORDER BY p.withdrawal_id DESC''',(a['_id'],))
            result['reports']=all_rows(c,'''SELECT r.report_id,r.service_date,g.name,r.created_at FROM leader_daily_report r JOIN leader_scope g ON g.scope_id=r.scope_id WHERE g.admin_id=%s ORDER BY r.service_date DESC LIMIT 100''',(a['_id'],))
            result['semesters']=all_rows(c,'SELECT semester_id,name,start_date,end_date,end_week FROM semester ORDER BY start_date DESC')
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
            a=self.actor(c,actor,('NORMAL',))
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
                WHERE a.status='ACTIVE' AND a.role='NORMAL' AND g.active=1 AND g.weekday IS NOT NULL ''')
            for scope in scopes:
                ids=[r['slot_id'] for r in all_rows(c,'''SELECT t.slot_id FROM service_slot t
                    WHERE t.business_id=%s AND t.weekday=%s ''',(scope['business_id'],scope['weekday']))]
                if not ids:continue
                marks=','.join(['%s']*len(ids))
                start=(scope['assigned_at'] or self.clock()).date()
                days=all_rows(c,f'''SELECT s.schedule_date,MAX(t.end_time) AS ends FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
                    WHERE s.slot_id IN ({marks}) AND s.status<>'CANCELLED' AND s.schedule_date BETWEEN %s AND %s
                    AND NOT EXISTS(SELECT 1 FROM leader_daily_report r WHERE r.scope_id=%s AND r.service_date=s.schedule_date)
                    GROUP BY s.schedule_date ORDER BY s.schedule_date''',ids+[start,self.clock().date(),scope['scope_id']])
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
                                 'businesses',rid)
            return {'created':count}
