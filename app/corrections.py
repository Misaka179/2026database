"""Audited attendance revisions and append-only credit reversal entries."""
from .db import Database, one, all_rows

MAX_SCORE = 2147483647


def migrate(settings):
    with Database(settings).transaction(True) as c:
        for table, name, definition in (
            ('student', 'credit_version', 'INT NOT NULL DEFAULT 1'),
            ('student', 'disabled_by_credit', 'TINYINT NOT NULL DEFAULT 0'),
            ('attendance', 'revision', 'INT NOT NULL DEFAULT 1'),
        ):
            c.execute(f'SHOW COLUMNS FROM {table} LIKE %s', (name,))
            if not c.fetchone():
                c.execute(f'ALTER TABLE {table} ADD {name} {definition}')
                if name == 'disabled_by_credit':
                    c.execute('''UPDATE student st SET disabled_by_credit=1
                        WHERE st.status='DISABLED' AND st.credit_score=0 AND EXISTS
                        (SELECT 1 FROM credit_log l WHERE l.student_id=st.student_id AND l.after_score=0)''')
        c.execute("SHOW COLUMNS FROM violation LIKE 'active_marker'")
        if not c.fetchone():
            c.execute('''ALTER TABLE violation ADD INDEX idx_violation_attendance(attendance_id),
                DROP INDEX uq_violation_attendance,
                ADD active_marker TINYINT GENERATED ALWAYS AS (CASE WHEN status='VALID' THEN 1 ELSE NULL END) STORED,
                ADD UNIQUE KEY uq_violation_active(attendance_id,active_marker)''')
        c.execute("SHOW COLUMNS FROM credit_log LIKE 'entry_type'")
        if not c.fetchone():
            c.execute('''ALTER TABLE credit_log
                MODIFY violation_id BIGINT UNSIGNED NULL, MODIFY rule_id BIGINT UNSIGNED NULL,
                ADD INDEX idx_credit_log_violation(violation_id), DROP INDEX uq_credit_log_violation,
                ADD entry_type VARCHAR(24) NOT NULL DEFAULT 'DEDUCTION',
                ADD reverses_log_id BIGINT UNSIGNED NULL,
                ADD UNIQUE KEY uq_credit_reversal(reverses_log_id),
                ADD CONSTRAINT fk_credit_reversal FOREIGN KEY(reverses_log_id) REFERENCES credit_log(credit_log_id)''')


class CorrectionService:
    def _set_credit_state(self, c, student, score):
        from .service import require
        require(0 <= score <= MAX_SCORE, '信用分超出可保存范围', 422)
        self.snapshot_memberships(c)
        status, credit_disabled = student['status'], student.get('disabled_by_credit', 0)
        if score == 0 and status == 'ACTIVE':
            status, credit_disabled = 'DISABLED', 1
        elif score > 0 and status == 'DISABLED' and credit_disabled:
            status, credit_disabled = 'ACTIVE', 0
        c.execute('''UPDATE student SET credit_score=%s,credit_version=credit_version+1,
            status=%s,disabled_by_credit=%s WHERE student_id=%s''',
            (score, status, credit_disabled, student['student_id']))
        cancelled = []
        if status == 'DISABLED' and credit_disabled:
            cancelled = self.cancel_future(c, student['student_id'], 'CREDIT')
        elif status == 'ACTIVE' and student['status'] == 'DISABLED' and student.get('disabled_by_credit'):
            # Restore only prospective work; never undo a manual cancellation or quit.
            c.execute("""UPDATE schedule SET cancel_reason='SYNC' WHERE student_id=%s
                AND status='CANCELLED' AND cancel_reason='CREDIT' AND schedule_date>=%s""",
                (student['student_id'], self.clock().date()))
            self.sync_semesters(c)
        return cancelled

    def _penalize(self, c, student_id, attendance_id, actual, admin_id, score):
        from .service import require
        rule = one(c, "SELECT * FROM credit_rule WHERE violation_type=%s AND status='ACTIVE'", (actual,))
        require(rule, '没有启用的扣分规则，考勤未保存')
        after = max(0, score - rule['deduct_score'])
        c.execute('INSERT INTO violation(attendance_id,rule_id,nominal_deduct) VALUES(%s,%s,%s)',
                  (attendance_id, rule['rule_id'], rule['deduct_score']))
        vid = c.lastrowid
        c.execute('''INSERT INTO credit_log(student_id,violation_id,rule_id,operator_id,
            change_score,before_score,after_score,change_reason,change_time)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (student_id, vid, rule['rule_id'], admin_id, after-score, score, after, actual, self.clock()))
        return after

    def correct_attendance(self, actor, schedule_id, status, reason, expected_revision):
        from .service import require, reason_text, instant
        reason = reason_text(reason)
        require(status in ('NORMAL','LATE','ABSENT','LEAVE'), '考勤状态无效', 422)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('NORMAL','SUPER','LEAD'))
            row = self.schedule(c, schedule_id)
            self.scope(a, row)
            self.attendance_kind_guard(row,status)
            existing = one(c, 'SELECT * FROM attendance WHERE schedule_id=%s FOR UPDATE', (schedule_id,))
            require(existing, '请先登记考勤，再进行改判', 404)
            require(row['status']=='COMPLETED' and (row.get('schedule_kind')=='WEEKLY' or instant(row['schedule_date'],row['end_time'])<=self.clock()),
                    '只能改判已经结束并结算的服务')
            if existing['attendance_status'] == status:
                return {'attendance_id': existing['attendance_id'], 'status': status, 'replayed': True}
            require(existing['revision'] == expected_revision, '考勤已被其他操作更新，请刷新后再改判')
            student = one(c, 'SELECT * FROM student WHERE student_id=%s FOR UPDATE', (row['student_id'],))
            before, score = student['credit_score'], student['credit_score']
            aid = existing['attendance_id']
            violations = all_rows(c, "SELECT * FROM violation WHERE attendance_id=%s AND status='VALID'", (aid,))
            refunded = 0
            for violation in violations:
                entries = all_rows(c, '''SELECT l.* FROM credit_log l WHERE l.violation_id=%s
                    AND l.entry_type='DEDUCTION' AND NOT EXISTS
                    (SELECT 1 FROM credit_log r WHERE r.reverses_log_id=l.credit_log_id)''', (violation['violation_id'],))
                for entry in entries:
                    restore = -entry['change_score']
                    require(0 <= score + restore <= MAX_SCORE, '冲正后的信用分超出可保存范围')
                    c.execute('''INSERT INTO credit_log(student_id,violation_id,rule_id,operator_id,
                        change_score,before_score,after_score,change_reason,change_time,entry_type,reverses_log_id)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'REVERSAL',%s)''',
                        (row['student_id'], violation['violation_id'], violation['rule_id'], a['_id'],
                         restore, score, score+restore, '考勤改判冲正：'+reason, self.clock(), entry['credit_log_id']))
                    score += restore
                    refunded += restore
                c.execute("UPDATE violation SET status='REVOKED' WHERE violation_id=%s", (violation['violation_id'],))
            if status in ('LATE','ABSENT'):
                score = self._penalize(c, row['student_id'], aid, status, a['_id'], score)
            # Fixed-slot manual increases do not survive attendance reclassification.
            if row.get('schedule_kind') == 'FIXED':
                row['service_minutes'] = self.slot(c, row['slot_id'])['service_minutes']
                c.execute('UPDATE schedule SET recognition_minutes=NULL WHERE schedule_id=%s', (schedule_id,))
            awarded = row['service_minutes'] if status in ('NORMAL','LATE') else 0
            record = one(c, 'SELECT * FROM service_record WHERE attendance_id=%s', (aid,))
            if record:
                c.execute('UPDATE service_record SET service_minutes=%s,record_status=%s WHERE attendance_id=%s',
                          (awarded, 'VALID' if awarded else 'VOID', aid))
            elif awarded:
                c.execute('INSERT INTO service_record(attendance_id,service_minutes) VALUES(%s,%s)', (aid,awarded))
            c.execute("""UPDATE attendance SET attendance_status=%s,admin_id=%s,remark=%s,
                check_time=%s,source='CORRECTED',revision=revision+1 WHERE attendance_id=%s""",
                (status,a['_id'],reason,self.clock(),aid))
            leaves = all_rows(c, "SELECT * FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'", (schedule_id,))
            if status != 'LEAVE':
                c.execute("UPDATE leave_application SET approve_status='CANCELLED' WHERE schedule_id=%s AND approve_status='APPROVED'", (schedule_id,))
            cancelled = self._set_credit_state(c, student, score)
            result = {'attendance_id':aid,'status':status,'revision':existing['revision']+1,
                      'service_minutes':awarded,'credit_before':before,'credit_score':score,
                      'refunded_score':refunded,'cancelled_schedules':cancelled}
            self.audit(c,a['_id'],'CORRECT_ATTENDANCE','attendance',aid,
                       {'attendance':existing,'credit_score':before,'service_record':record,'approved_leaves':leaves},result,reason)
            return result

    def set_student_credit(self, actor, student_id, credit_score, expected_version, reason):
        from .service import require, reason_text
        reason = reason_text(reason)
        require(isinstance(credit_score,int) and not isinstance(credit_score,bool) and 0<=credit_score<=MAX_SCORE,
                '信用分须为非负整数',422)
        with self.db.transaction(True) as c:
            a = self.actor(c,actor,('SUPER',))
            student = one(c,'SELECT * FROM student WHERE student_id=%s FOR UPDATE',(student_id,))
            require(student,'队员不存在',404)
            if student['credit_score']==credit_score:
                return {'student_id':student_id,'credit_score':credit_score,'replayed':True}
            require(student['credit_version']==expected_version,'信用分已更新，请刷新后重新调整')
            before = student['credit_score']
            c.execute('''INSERT INTO credit_log(student_id,operator_id,change_score,before_score,after_score,
                change_reason,change_time,entry_type) VALUES(%s,%s,%s,%s,%s,%s,%s,'MANUAL_SET')''',
                (student_id,a['_id'],credit_score-before,before,credit_score,'超级管理员调分：'+reason,self.clock()))
            cancelled = self._set_credit_state(c,student,credit_score)
            self.audit(c,a['_id'],'SET_STUDENT_CREDIT','student',student_id,
                       {'credit_score':before,'status':student['status']},
                       {'credit_score':credit_score,'cancelled_schedules':cancelled},reason)
            return {'student_id':student_id,'credit_score':credit_score,'credit_version':student['credit_version']+1}
