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
        from .business_schema import installed as multi_installed
        multi = multi_installed(c)
        for day in range(1,8):
            for period,(start,end) in enumerate(TIMES,1):
                if not one(c,'SELECT slot_id FROM service_slot WHERE weekday=%s AND period_no=%s' + (" AND business_id=(SELECT business_id FROM business WHERE code='CONSULT')" if multi else ''),(day,period)):
                    c.execute('''INSERT INTO service_slot(team_name,weekday,period_no,start_time,end_time,
                        need_num,service_minutes,manager_admin_id)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,NULL)''',
                        (slot_name(day,period),day,period,start,end,capacity,180 if period==3 else 120))
    from .semester import migrate as migrate_semesters
    migrate_semesters(settings)
    from .admin_roles import migrate as migrate_admin_roles
    migrate_admin_roles(settings)
    from .business_schema import migrate as migrate_business
    migrate_business(settings)
    from .collection_schema import migrate as migrate_collections
    migrate_collections(settings)
    from .collection_governance_schema import migrate as migrate_collection_governance
    migrate_collection_governance(settings)
    from .directory_schema import migrate as migrate_directory
    migrate_directory(settings)
    from .hour_units import migrate as migrate_hour_units
    migrate_hour_units(settings)
    from .leaders import migrate as migrate_leaders
    migrate_leaders(settings)
    _delete_unreferenced_legacy_slots(settings)
    _drop_slot_status(settings)
    return {'fixed_slots':84,'weekly_posts':2}


def _delete_unreferenced_legacy_slots(settings):
    """Retire old no-weekday catalogue rows once nothing references them."""
    db=Database(settings)
    with db.transaction(True) as c:
        c.execute("SHOW COLUMNS FROM service_slot LIKE 'schedule_kind'")
        if not c.fetchone():
            return
        c.execute('''DELETE t FROM service_slot t
            WHERE t.weekday IS NULL AND t.schedule_kind IN ('LEGACY','FIXED')
              AND EXISTS(SELECT 1 FROM business b WHERE b.business_id=t.business_id AND b.status='ACTIVE')
              AND NOT EXISTS(SELECT 1 FROM schedule s WHERE s.slot_id=t.slot_id)
              AND NOT EXISTS(SELECT 1 FROM slot_member m WHERE m.slot_id=t.slot_id)
              AND NOT EXISTS(SELECT 1 FROM semester_member sm WHERE sm.slot_id=t.slot_id)
              AND NOT EXISTS(SELECT 1 FROM transfer_application p
                             WHERE p.old_slot_id=t.slot_id OR p.new_slot_id=t.slot_id)''')


def _drop_slot_status(settings):
    """Remove the retired service_slot.status concept, preserving its index."""
    db=Database(settings)
    with db.transaction(True) as c:
        c.execute("SHOW INDEX FROM service_slot WHERE Key_name='idx_slot_manager'")
        if not c.fetchone():
            c.execute('ALTER TABLE service_slot ADD INDEX idx_slot_manager(manager_admin_id)')
        c.execute("SHOW INDEX FROM service_slot WHERE Key_name='idx_slot_manager_status'")
        if c.fetchone():
            c.execute('ALTER TABLE service_slot DROP INDEX idx_slot_manager_status')
        c.execute("SHOW COLUMNS FROM service_slot LIKE 'status'")
        if c.fetchone():
            c.execute('ALTER TABLE service_slot DROP COLUMN status')


def installed(c):
    c.execute("SHOW COLUMNS FROM service_slot LIKE 'weekday'")
    return c.fetchone() is not None
