"""Versioned half-hour collection policy; legacy records retain minute precision."""
from .db import Database,one


def migrate(settings):
    with Database(settings).transaction() as c:
        c.execute("SHOW COLUMNS FROM hour_collection LIKE 'minute_step'")
        ready=bool(c.fetchone())
    if not ready and settings.get('database')=='volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        c.execute("SHOW COLUMNS FROM hour_collection LIKE 'minute_step'")
        if not c.fetchone():c.execute('ALTER TABLE hour_collection ADD minute_step INT NOT NULL DEFAULT 1')
        c.execute("INSERT IGNORE INTO feature_migration VALUES('collection_half_hours_v1',NOW())")


def validate_half_hour(value):
    from .service import require
    require(type(value)==int and 30<=value<=1440 and value%30==0,
            '时长须为0.5小时的倍数，范围为0.5至24小时（30至1440分钟）',422)


def record_step(c,record_id):
    c.execute("SHOW TABLES LIKE 'hour_collection'")
    if not c.fetchone():return 1
    row=one(c,'''SELECT h.minute_step FROM service_record r JOIN attendance a ON a.attendance_id=r.attendance_id
      JOIN hour_submission s ON s.schedule_id=a.schedule_id JOIN collection_item i ON i.item_id=s.item_id
      JOIN hour_collection h ON h.collection_id=i.collection_id WHERE r.record_id=%s''',(record_id,))
    return row['minute_step'] if row else 1
