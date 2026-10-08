"""Semester calendars, dated membership history and weekly settlement.

Dates use the service's Shanghai clock. Initial rosters start on the term start.
All mutations run under the same writer lock as attendance and approvals.
"""
from datetime import date, datetime, time, timedelta
from .db import Database, one, all_rows

HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html'
HOLIDAYS = [
    ('2026-01-01', '2026-01-03', '元旦'),
    ('2026-02-15', '2026-02-23', '春节'),
    ('2026-04-04', '2026-04-06', '清明节'),
    ('2026-05-01', '2026-05-05', '劳动节'),
    ('2026-06-19', '2026-06-21', '端午节'),
    ('2026-09-25', '2026-09-27', '中秋节'),
    ('2026-10-01', '2026-10-07', '国庆节'),
]
MAKEUP_DAYS = {'2026-01-04', '2026-02-14', '2026-02-28',
               '2026-05-09', '2026-09-20', '2026-10-10'}


def monday(day):
    return day - timedelta(days=day.weekday())


def end_date(start, weeks):
    return monday(start) + timedelta(weeks=weeks, days=-1)


def dates(start, end):
    for n in range((end - start).days + 1):
        yield start + timedelta(days=n)


def default_day(day):
    if day.year != 2026:
        return 'UNCONFIRMED', None, '该年份尚无内置节假日数据，请管理员核对日历'
    for start, end, name in HOLIDAYS:
        if date.fromisoformat(start) <= day <= date.fromisoformat(end):
            return 'HOLIDAY', None, name
    if day.isoformat() in MAKEUP_DAYS:
        return 'MAKEUP_REQUIRED', None, '调休补班日，请指定执行周几的班表'
    return 'NORMAL', day.isoweekday(), '按每周固定班次'


def installed(c):
    c.execute("SHOW TABLES LIKE 'semester'")
    return bool(c.fetchone())


def migrate(settings):
    with Database(settings).transaction(True) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS semester (
            semester_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL, start_date DATE NOT NULL,
            end_week INT NOT NULL, end_date DATE NOT NULL,
            admin_id BIGINT UNSIGNED NOT NULL, issues JSON NULL,
            last_settled_at DATETIME(6) NULL,
            FOREIGN KEY (admin_id) REFERENCES admin(admin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        c.execute('''CREATE TABLE IF NOT EXISTS semester_day (
            semester_id BIGINT UNSIGNED NOT NULL, service_date DATE NOT NULL,
            mode VARCHAR(24) NOT NULL, effective_weekday TINYINT NULL,
            note VARCHAR(500) NOT NULL, is_manual TINYINT NOT NULL DEFAULT 0,
            PRIMARY KEY (semester_id, service_date),
            FOREIGN KEY (semester_id) REFERENCES semester(semester_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        c.execute("SHOW COLUMNS FROM semester LIKE 'members_initialized'")
        if not c.fetchone():
            c.execute('ALTER TABLE semester ADD members_initialized TINYINT NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS semester_member (
            membership_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            semester_id BIGINT UNSIGNED NOT NULL, student_id VARCHAR(32) NOT NULL,
            slot_id BIGINT UNSIGNED NOT NULL, effective_from DATETIME(6) NOT NULL,
            effective_until DATETIME(6) NULL,
            active_marker TINYINT GENERATED ALWAYS AS
                (CASE WHEN effective_until IS NULL THEN 1 ELSE NULL END) STORED,
            UNIQUE KEY uq_semester_member(semester_id,student_id,slot_id,active_marker),
            FOREIGN KEY(semester_id) REFERENCES semester(semester_id),
            FOREIGN KEY(student_id) REFERENCES student(student_id),
            FOREIGN KEY(slot_id) REFERENCES service_slot(slot_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        columns = {
            'semester_id': 'BIGINT UNSIGNED NULL', 'week_no': 'INT NULL',
            'cancel_reason': 'VARCHAR(24) NULL',
        }
        for name, sql in columns.items():
            c.execute('SHOW COLUMNS FROM schedule LIKE %s', (name,))
            if not c.fetchone():
                c.execute(f'ALTER TABLE schedule ADD {name} {sql}')
        if not one(c, '''SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='schedule'
            AND CONSTRAINT_NAME='fk_schedule_semester' '''):
            c.execute('''ALTER TABLE schedule ADD INDEX idx_schedule_semester(semester_id,schedule_date),
                ADD CONSTRAINT fk_schedule_semester FOREIGN KEY(semester_id) REFERENCES semester(semester_id)''')
        c.execute("SHOW COLUMNS FROM attendance LIKE 'source'")
        if not c.fetchone():
            c.execute("ALTER TABLE attendance ADD source VARCHAR(24) NOT NULL DEFAULT 'MANUAL'")
        # Preserve past decisions; outstanding one-off transfers can no longer execute.
        c.execute("""UPDATE transfer_application SET final_status='CANCELLED'
            WHERE old_slot_id IS NULL AND final_status='PENDING' AND first_status<>'REJECTED'""")
    from .corrections import migrate as migrate_corrections
    migrate_corrections(settings)


class SemesterService:
    def semesters(self, actor):
        with self.db.transaction() as c:
            a = self.actor(c, actor)
            if not installed(c):
                return []
            rows = list(all_rows(c, 'SELECT * FROM semester ORDER BY start_date DESC'))
            today = self.clock().date()
            for row in rows:
                if a['_role'] != 'SUPER':
                    row['issues'] = []
                row['current_week'] = (0 if today < row['start_date'] else
                    min(row['end_week'], (today - monday(row['start_date'])).days // 7 + 1))
                row['phase'] = 'UPCOMING' if today < row['start_date'] else 'ENDED' if today > row['end_date'] else 'ONGOING'
                row['calendar'] = all_rows(c, 'SELECT * FROM semester_day WHERE semester_id=%s ORDER BY service_date', (row['semester_id'],))
                row['holiday_source'] = HOLIDAY_SOURCE
            return rows

    def save_semester(self, actor, name, start_date, end_week, semester_id=None):
        import json
        from .service import require, parse_date
        start = parse_date(start_date)
        require(name.strip() and len(name) <= 100, '请填写学期名称', 422)
        require(isinstance(end_week, int) and 1 <= end_week <= 53, '结束周次须为 1 至 53', 422)
        end = end_date(start, end_week)
        now = self.clock()
        require(end >= now.date(), '学期结束日期不能早于今天', 422)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            before = None
            if semester_id is not None:
                before = one(c, 'SELECT * FROM semester WHERE semester_id=%s', (semester_id,))
                require(before, '学期不存在', 404)
                require(before['start_date'] > now.date() or before['start_date'] == start,
                        '学期开始后不能修改开工日期，只能调整结束周次')
            require(not one(c, '''SELECT 1 FROM semester WHERE start_date<=%s AND end_date>=%s
                AND (%s IS NULL OR semester_id<>%s)''', (end, start, semester_id, semester_id)), '学期日期不能重叠')
            if before:
                c.execute('UPDATE semester SET name=%s,start_date=%s,end_week=%s,end_date=%s WHERE semester_id=%s',
                          (name.strip(), start, end_week, end, semester_id))
                if before['start_date'] != start:
                    c.execute('UPDATE semester_member SET effective_from=%s WHERE semester_id=%s AND effective_from=%s',
                              (datetime.combine(start,time()),semester_id,datetime.combine(before['start_date'],time())))
            else:
                c.execute('INSERT INTO semester(name,start_date,end_week,end_date,admin_id) VALUES(%s,%s,%s,%s,%s)',
                          (name.strip(), start, end_week, end, a['_id']))
                semester_id = c.lastrowid
            c.execute('DELETE FROM semester_day WHERE semester_id=%s AND (service_date<%s OR service_date>%s)', (semester_id, start, end))
            existing = {r['service_date'] for r in all_rows(c, 'SELECT service_date FROM semester_day WHERE semester_id=%s', (semester_id,))}
            for day in dates(start, end):
                if day not in existing:
                    mode, weekday, note = default_day(day)
                    c.execute('INSERT INTO semester_day(semester_id,service_date,mode,effective_weekday,note) VALUES(%s,%s,%s,%s,%s)',
                              (semester_id, day, mode, weekday, note))
            result = self._sync_semester(c, semester_id)
            result['settled'] = self._settle_weeks(c)['settled']
            self.audit(c, a['_id'], 'SAVE_SEMESTER', 'semester', semester_id, before,
                       {'name': name, 'start_date': start, 'end_week': end_week, 'end_date': end, **result})
            return {'semester_id': semester_id, 'end_date': end, **result}

    def set_calendar(self, actor, semester_id, start_date, end_date, mode, weekday=None, reason=''):
        from .service import require, parse_date, reason_text, instant
        start, end = parse_date(start_date), parse_date(end_date)
        reason = reason_text(reason)
        require(start <= end, '结束日期不能早于开始日期', 422)
        require(mode in ('DEFAULT', 'REST', 'WEEKDAY', 'NATURAL'), '日历设置类型无效', 422)
        require(mode != 'WEEKDAY' or isinstance(weekday, int) and 1 <= weekday <= 7,
                '请选择周一至周日的班表', 422)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            term = one(c, 'SELECT * FROM semester WHERE semester_id=%s', (semester_id,))
            require(term, '学期不存在', 404)
            require(term['start_date'] <= start <= end <= term['end_date'], '日期必须在本学期内', 422)
            before = all_rows(c, 'SELECT * FROM semester_day WHERE semester_id=%s AND service_date BETWEEN %s AND %s', (semester_id, start, end))
            for old in before:
                if datetime.combine(old['service_date'],time(8,15)) <= self.clock():
                    require(old['mode'] in ('MAKEUP_REQUIRED','UNCONFIRMED') and old['effective_weekday'] is None,
                            '已开始或过去的日期只能补齐待确认日历，不能改写既有安排')
                    require(not one(c,"SELECT 1 FROM schedule WHERE schedule_date=%s AND status IN ('ACTIVE','COMPLETED')",(old['service_date'],)),
                            '该日期已有服务记录，不能追溯修改日历')
            for day in dates(start, end):
                kind, effective, note = default_day(day) if mode == 'DEFAULT' else (
                    ('REST', None, reason) if mode == 'REST' else
                    ('CUSTOM', weekday if mode == 'WEEKDAY' else day.isoweekday(), reason))
                c.execute('UPDATE semester_day SET mode=%s,effective_weekday=%s,note=%s,is_manual=%s WHERE semester_id=%s AND service_date=%s',
                          (kind, effective, note, mode != 'DEFAULT', semester_id, day))
            result = self._sync_semester(c, semester_id)
            result['settled'] = self._settle_weeks(c)['settled']
            self.audit(c, a['_id'], 'SET_CALENDAR', 'semester', semester_id, before,
                       {'start_date': start, 'end_date': end, 'mode': mode, 'weekday': weekday, **result}, reason)
            return result

    def _snapshot_members(self, c, term):
        """Freeze the initial roster from term start; date every later change."""
        current = {(r['student_id'],r['slot_id']) for r in all_rows(c, '''SELECT m.*
            FROM slot_member m JOIN student s ON s.student_id=m.student_id
            JOIN service_slot t ON t.slot_id=m.slot_id
            WHERE s.status='ACTIVE' AND t.weekday IS NOT NULL AND t.status='ACTIVE' ''')}
        open_rows = all_rows(c, 'SELECT * FROM semester_member WHERE semester_id=%s AND effective_until IS NULL', (term['semester_id'],))
        previous = {(r['student_id'],r['slot_id']) for r in open_rows}
        effective = datetime.combine(term['start_date'],time())
        if term['members_initialized']:
            effective = max(effective,self.clock())
        for row in open_rows:
            if (row['student_id'],row['slot_id']) not in current:
                c.execute('UPDATE semester_member SET effective_until=%s WHERE membership_id=%s',
                          (max(effective,row['effective_from']),row['membership_id']))
        for student, slot in current - previous:
            c.execute('INSERT INTO semester_member(semester_id,student_id,slot_id,effective_from) VALUES(%s,%s,%s,%s)',
                      (term['semester_id'],student,slot,effective))
        if not term['members_initialized']:
            c.execute('UPDATE semester SET members_initialized=1 WHERE semester_id=%s',(term['semester_id'],))

    def snapshot_memberships(self, c):
        if installed(c):
            for term in all_rows(c,'SELECT * FROM semester WHERE end_date>=%s',(self.clock().date(),)):
                self._snapshot_members(c,term)

    def _sync_semester(self, c, semester_id):
        """Backfill missing term work; keep attendance, cancellations and roster dates."""
        import json
        from .service import instant, minutes
        term = one(c, 'SELECT * FROM semester WHERE semester_id=%s', (semester_id,))
        now = self.clock()
        self._snapshot_members(c,term)
        days = all_rows(c, 'SELECT * FROM semester_day WHERE semester_id=%s', (semester_id,))
        members = all_rows(c, '''SELECT m.student_id,m.effective_from,m.effective_until,t.*,ad.status AS manager_status FROM semester_member m
            JOIN service_slot t ON t.slot_id=m.slot_id
            LEFT JOIN admin ad ON ad.admin_id=t.manager_admin_id
            WHERE m.semester_id=%s AND t.weekday IS NOT NULL''',(semester_id,))
        counts = {}
        for member in members:
            if member['effective_until'] is None:
                counts[member['slot_id']] = counts.get(member['slot_id'], 0) + 1
        issues = set()
        desired = {}
        for day in days:
            if day['mode'] in ('MAKEUP_REQUIRED', 'UNCONFIRMED'):
                issues.add(f"{day['service_date']}：{day['note']}")
            if day['effective_weekday'] is None:
                continue
            for member in members:
                begins = instant(day['service_date'],member['start_time'])
                if member['weekday'] != day['effective_weekday'] or begins < member['effective_from'] or (member['effective_until'] is not None and begins >= member['effective_until']):
                    continue
                if member['manager_status'] != 'ACTIVE' or member['need_num'] is None or counts.get(member['slot_id'],0) > member['need_num']:
                    issues.add(f"{member['team_name']}：负责人或容量待完善；已有固定队员照常排班计时")
                desired[(member['student_id'], member['slot_id'], day['service_date'])] = member
        existing = all_rows(c, '''SELECT s.*,t.start_time,t.end_time FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
            WHERE s.semester_id=%s OR (s.schedule_date BETWEEN %s AND %s)''',
            (semester_id, term['start_date'], term['end_date']))
        created = cancelled = 0
        live = {}
        blocked = set()
        for row in existing:
            key = row['student_id'], row['slot_id'], row['schedule_date']
            if row['status'] == 'CANCELLED':
                if row.get('cancel_reason') in ('MANUAL','CREDIT','QUIT') or instant(row['schedule_date'],row['start_time']) <= now:
                    blocked.add(key)
                continue
            if row['semester_id'] == semester_id and key not in desired and instant(row['schedule_date'], row['start_time']) > now:
                c.execute("UPDATE schedule SET status='CANCELLED',cancel_reason='SYNC' WHERE schedule_id=%s", (row['schedule_id'],))
                c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status IN ('PENDING','APPROVED')", (row['schedule_id'],))
                cancelled += 1
            else:
                live[key] = row
        from collections import defaultdict
        by_day = defaultdict(list)
        for key, row in live.items():
            by_day[key[2]].append(row)
        for key, member in desired.items():
            sid, slot, day = key
            week = (day - monday(term['start_date'])).days // 7 + 1
            if key in live:
                if live[key]['semester_id'] is None:
                    c.execute('UPDATE schedule SET semester_id=%s,week_no=%s WHERE schedule_id=%s', (semester_id, week, live[key]['schedule_id']))
                continue
            if key in blocked:
                continue
            peers = by_day[day]
            if any(r['student_id'] == sid and minutes(r['start_time']) < minutes(member['end_time']) and minutes(member['start_time']) < minutes(r['end_time']) for r in peers):
                issues.add(f'{day}：{sid} 有时间冲突，请核对排班')
                continue
            # Capacity limits new assignments/transfers, not credit for an existing roster.
            c.execute('''INSERT INTO schedule(student_id,slot_id,admin_id,schedule_date,semester_id,week_no)
                VALUES(%s,%s,%s,%s,%s,%s)''', (sid, slot, term['admin_id'], day, semester_id, week))
            live[key] = {**member, 'schedule_date': day}
            peers.append(live[key])
            created += 1
        c.execute('UPDATE semester SET issues=%s WHERE semester_id=%s', (json.dumps(sorted(issues), ensure_ascii=False), semester_id))
        return {'created': created, 'cancelled': cancelled, 'issues': sorted(issues)}

    def sync_semesters(self, c, strict_student=None):
        from .service import require
        if installed(c):
            for row in all_rows(c, 'SELECT semester_id FROM semester WHERE end_date>=%s', (self.clock().date(),)):
                result = self._sync_semester(c, row['semester_id'])
                if strict_student:
                    require(not any(f'：{strict_student} 有时间冲突' in issue for issue in result['issues']),
                            '目标固定班次与已有日期排班时间冲突，换班未生效')

    def run_weekly_settlement(self):
        """Repair missing dated work, then settle elapsed weeks exactly once."""
        with self.db.transaction(True) as c:
            if not installed(c):
                return {'settled': 0}
            for term in all_rows(c,'SELECT semester_id FROM semester ORDER BY start_date'):
                self._sync_semester(c,term['semester_id'])
            return self._settle_weeks(c)

    def _settle_weeks(self, c):
        # Called under the same writer lock and transaction as schedule reconciliation.
        now = self.clock()
        cutoff = monday(now.date())
        rows = all_rows(c, '''SELECT s.*,t.end_time,t.service_minutes,sem.admin_id AS owner
            FROM schedule s JOIN service_slot t ON t.slot_id=s.slot_id
            JOIN semester sem ON sem.semester_id=s.semester_id
            LEFT JOIN attendance a ON a.schedule_id=s.schedule_id
            WHERE s.status='ACTIVE' AND s.schedule_date<%s AND a.attendance_id IS NULL
            ORDER BY s.schedule_date,s.schedule_id''', (cutoff,))
        for row in rows:
            leave = one(c, "SELECT leave_id FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'", (row['schedule_id'],))
            actual = 'LEAVE' if leave else 'NORMAL'
            c.execute('''INSERT INTO attendance(schedule_id,admin_id,attendance_status,check_time,remark,source)
                VALUES(%s,%s,%s,%s,%s,'AUTO_WEEKLY')''',
                (row['schedule_id'], row['owner'], actual, now, '系统按周自动结算；管理员可补录缺勤或迟到'))
            aid = c.lastrowid
            if actual == 'NORMAL':
                c.execute('INSERT INTO service_record(attendance_id,service_minutes) VALUES(%s,%s)', (aid, row['service_minutes']))
            c.execute("UPDATE schedule SET status='COMPLETED' WHERE schedule_id=%s", (row['schedule_id'],))
            c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status='PENDING'", (row['schedule_id'],))
        owners = {r['semester_id']: r['owner'] for r in rows}
        for term, owner in owners.items():
            total = sum(r['semester_id'] == term for r in rows)
            c.execute('UPDATE semester SET last_settled_at=%s WHERE semester_id=%s', (now, term))
            self.audit(c, owner, 'AUTO_WEEKLY_SETTLEMENT', 'semester', term,
                       after={'settled': total, 'before_date': cutoff}, reason='系统自动结算已结束周次')
        return {'settled': len(rows)}

    def sync_calendar(self, actor, semester_id):
        from .service import require
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            require(one(c, 'SELECT 1 FROM semester WHERE semester_id=%s', (semester_id,)), '学期不存在', 404)
            result = self._sync_semester(c, semester_id)
            result['settled'] = self._settle_weeks(c)['settled']
            self.audit(c, a['_id'], 'SYNC_SEMESTER', 'semester', semester_id, after=result)
            return result
