"""Idempotent, non-destructive upgrade to the weekly 35-slot catalogue."""
from .db import Database, one
from .roster import TIMES, slot_name


def migrate(settings, capacity=None):
    db=Database(settings)
    with db.transaction(True) as c:
        c.execute("SHOW COLUMNS FROM service_slot LIKE 'weekday'")
        if not c.fetchone():
            c.execute('ALTER TABLE service_slot ADD weekday TINYINT NULL, MODIFY manager_admin_id BIGINT UNSIGNED NULL, MODIFY need_num INT NULL, ADD UNIQUE KEY uq_weekly_slot (weekday,period_no)')
        c.execute('''CREATE TABLE IF NOT EXISTS slot_member (
            student_id VARCHAR(32) NOT NULL, slot_id BIGINT UNSIGNED NOT NULL,
            PRIMARY KEY(student_id,slot_id), INDEX idx_member_slot(slot_id),
            CONSTRAINT fk_member_student FOREIGN KEY(student_id) REFERENCES student(student_id),
            CONSTRAINT fk_member_slot FOREIGN KEY(slot_id) REFERENCES service_slot(slot_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        c.execute("SHOW COLUMNS FROM transfer_application LIKE 'old_slot_id'")
        if not c.fetchone():
            c.execute('''ALTER TABLE transfer_application
                MODIFY old_schedule_id BIGINT UNSIGNED NULL, MODIFY new_date DATE NULL,
                ADD old_slot_id BIGINT UNSIGNED NULL,
                ADD CONSTRAINT fk_transfer_old_slot FOREIGN KEY(old_slot_id) REFERENCES service_slot(slot_id),
                ADD UNIQUE KEY uq_fixed_transfer_pending(student_id,old_slot_id,active_marker)''')
        # Old slots remain available to historical foreign keys, not new choices.
        c.execute("UPDATE service_slot SET status='DISABLED' WHERE weekday IS NULL")
        for day in range(1,8):
            for period,(start,end) in enumerate(TIMES,1):
                if not one(c,'SELECT slot_id FROM service_slot WHERE weekday=%s AND period_no=%s',(day,period)):
                    c.execute('''INSERT INTO service_slot(team_name,weekday,period_no,start_time,end_time,
                        location,need_num,service_minutes,manager_admin_id)
                        VALUES(%s,%s,%s,%s,%s,'图书馆',%s,%s,NULL)''',
                        (slot_name(day,period),day,period,start,end,capacity,180 if period==3 else 120))
    from .semester import migrate as migrate_semesters
    migrate_semesters(settings)
    from .admin_roles import migrate as migrate_admin_roles
    migrate_admin_roles(settings)
    return {'fixed_slots':35}


def installed(c):
    c.execute("SHOW COLUMNS FROM service_slot LIKE 'weekday'")
    return c.fetchone() is not None
