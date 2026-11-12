"""Administrator accounts are created directly by a SUPER.

There is intentionally no "promote a volunteer into an administrator" path:
administrator accounts and volunteer accounts are independent identities.
"""
from .db import Database, one


def migrate(settings):
    with Database(settings).transaction(True) as c:
        c.execute("SHOW COLUMNS FROM admin LIKE 'student_id'")
        if not c.fetchone():
            c.execute('''ALTER TABLE admin ADD student_id VARCHAR(32) NULL,
                ADD UNIQUE KEY uq_admin_student(student_id),
                ADD CONSTRAINT fk_admin_student FOREIGN KEY(student_id) REFERENCES student(student_id)''')


class AdministratorService:
    def increase_fixed_hours(self, actor, schedule_id, service_minutes, expected_minutes, reason):
        """Save a fixed-slot override; unrecognised work stays in weekly settlement."""
        from .service import require, reason_text, instant
        reason = reason_text(reason)
        require(type(service_minutes) is int and 1 <= service_minutes <= 1440,
                '认定时长须为 1 至 1440 的整数分钟', 422)
        require(type(expected_minutes) is int, '请刷新后重试', 422)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('NORMAL',))
            row = self.schedule(c, schedule_id)
            self.scope(a, row)
            require(row.get('schedule_kind') == 'FIXED', '仅可上调固定时段服务时长', 422)
            require(row['status'] in ('ACTIVE', 'COMPLETED') and
                    instant(row['schedule_date'], row['end_time']) <= self.clock(),
                    '仅可调整已结束且未取消的服务', 422)
            attendance = one(c, 'SELECT * FROM attendance WHERE schedule_id=%s FOR UPDATE', (schedule_id,))
            require(not attendance or attendance['attendance_status'] in ('NORMAL', 'LATE'),
                    '缺勤或请假不能上调时长，请先核实考勤', 422)
            require(not one(c, "SELECT 1 FROM leave_application WHERE schedule_id=%s AND approve_status='APPROVED'", (schedule_id,)),
                    '已批准请假的服务不能上调时长', 422)
            record = one(c, 'SELECT * FROM service_record WHERE attendance_id=%s FOR UPDATE',
                         (attendance['attendance_id'],)) if attendance else None
            require(not attendance or record and record['record_status'] == 'VALID',
                    '没有有效服务记录，请先核实考勤', 422)
            current = record['service_minutes'] if record else row['service_minutes']
            require(current == expected_minutes, '时长已发生变化，请刷新后重新调整')
            require(service_minutes > current, '普通管理员只能提高当前时长，不能降低或保持不变', 422)
            c.execute('UPDATE schedule SET recognition_minutes=%s WHERE schedule_id=%s', (service_minutes, schedule_id))
            if record:
                c.execute('UPDATE service_record SET service_minutes=%s WHERE record_id=%s', (service_minutes, record['record_id']))
            result = {'schedule_id': schedule_id, 'student_id': row['student_id'],
                      'service_minutes': service_minutes, 'settled': bool(record)}
            log_id = self.audit(c, a['_id'], 'INCREASE_FIXED_HOURS', 'schedule', schedule_id,
                                {'service_minutes': current}, result, reason)
            recipients = self._super_recipients(c)
            if hasattr(self, 'fixed_hour_recipients'):
                recipients = self.fixed_hour_recipients(c, row['slot_id'])
            message = (f"学号 {row['student_id']}，{row['schedule_date']} {row.get('business_name', '')}："
                       f"{current} 分钟上调至 {service_minutes} 分钟。说明：{reason}。"
                       + ('已更新有效记录。' if record else '待周结算入账。'))
            self._notice(c, recipients, f'increase-fixed-hours:{log_id}', 'SERVICE',
                         '时段管理员上调服务时长', message, 'schedules', schedule_id)
            self._notice(c, [('student', row['student_id'])], f'increase-fixed-hours:{log_id}',
                         'SERVICE', '服务时长已上调', message, 'schedules', schedule_id)
            return result
