"""Additive multi-business migration. Never rebuild existing accounting tables."""
from .db import Database, one


def installed(c):
    c.execute("SHOW COLUMNS FROM service_slot LIKE 'business_id'")
    return bool(c.fetchone())


CATALOG = [('CONSULT', '咨询服务', 'FIXED', 'SLOT'),
           ('ART', '美育', 'FIXED', 'SLOT'), ('PUBLICITY', '青广宣传', 'FIXED', 'BUSINESS'),
           ('GARDEN', '开心花园', 'WEEKLY', 'BUSINESS')]
ART = [('08:30','09:55',120),('10:15','11:30',120),('14:00','16:25',180),('16:45','18:00',120)]
PUBLICITY = [('11:30','13:30',180),('16:35','18:35',150),('18:35','19:35',120)]


def migrate(settings):
    # Do not depend on a caller remembering to back up before DDL (MySQL DDL auto-commits).
    if settings.get('database')=='volunteer_core':
        with Database(settings).transaction() as check:
            check.execute("SHOW TABLES LIKE 'feature_migration'")
            ready=bool(check.fetchone()) and bool(one(check,"SELECT 1 FROM feature_migration WHERE name='multi_business_v1'"))
        if not ready:
            from .backup import backup_database
            backup_database(settings)
    with Database(settings).transaction(True) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS business (
            business_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(32) NULL UNIQUE, name VARCHAR(100) NOT NULL UNIQUE,
            kind VARCHAR(16) NOT NULL, manager_scope VARCHAR(16) NOT NULL,
            manager_admin_id BIGINT UNSIGNED NULL,
            FOREIGN KEY(manager_admin_id) REFERENCES admin(admin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        for code, name, kind, scope in CATALOG:
            c.execute('INSERT IGNORE INTO business(code,name,kind,manager_scope) VALUES(%s,%s,%s,%s)', (code,name,kind,scope))
        for name in ('明远学术汇','讲解队','钢琴队','古筝队','科研探索','干部'):
            if name=='干部' and one(c,"SELECT 1 FROM business WHERE name='干部及干事'"):continue
            c.execute("INSERT IGNORE INTO business(name,kind,manager_scope) VALUES(%s,'EVENT','NONE')", (name,))
        consult = one(c,"SELECT business_id FROM business WHERE code='CONSULT'")['business_id']
        additions = [
            ('service_slot','business_id',f'BIGINT UNSIGNED NOT NULL DEFAULT {consult}'),
            ('service_slot','schedule_kind',"VARCHAR(16) NOT NULL DEFAULT 'FIXED'"),
            ('schedule','recognition_minutes','INT NULL'),
            ('schedule','source_key','VARCHAR(160) NULL'),
            ('schedule','weekly_confirmed','TINYINT NOT NULL DEFAULT 1'),
            ('leave_application','rejection_reason',"VARCHAR(500) NOT NULL DEFAULT ''"),
        ]
        for table, col, definition in additions:
            c.execute(f'SHOW COLUMNS FROM {table} LIKE %s',(col,))
            if not c.fetchone(): c.execute(f'ALTER TABLE {table} ADD {col} {definition}')
        c.execute("SHOW INDEX FROM service_slot WHERE Key_name='uq_weekly_slot'")
        if c.fetchone(): c.execute('ALTER TABLE service_slot DROP INDEX uq_weekly_slot')
        c.execute("SHOW INDEX FROM service_slot WHERE Key_name='uq_business_slot'")
        if not c.fetchone():
            c.execute('ALTER TABLE service_slot ADD UNIQUE KEY uq_business_slot(business_id,weekday,period_no)')
        c.execute("SHOW INDEX FROM schedule WHERE Key_name='uq_schedule_source'")
        if not c.fetchone(): c.execute('ALTER TABLE schedule ADD UNIQUE KEY uq_schedule_source(source_key)')
        c.execute("SHOW COLUMNS FROM service_slot LIKE 'start_time'")
        if c.fetchone()['Null']=='NO':
            c.execute('ALTER TABLE service_slot MODIFY start_time TIME NULL, MODIFY end_time TIME NULL')
        c.execute("UPDATE service_slot SET schedule_kind='LEGACY' WHERE business_id=%s AND weekday IS NULL AND schedule_kind='FIXED'",(consult,))
        for code, periods in [('ART',ART),('PUBLICITY',PUBLICITY)]:
            biz = one(c,'SELECT * FROM business WHERE code=%s',(code,))
            for day in range(1,8):
                for period,(start,end,duration) in enumerate(periods,1):
                    if not one(c,'SELECT 1 FROM service_slot WHERE business_id=%s AND weekday=%s AND period_no=%s',(biz['business_id'],day,period)):
                        c.execute('''INSERT INTO service_slot(business_id,team_name,weekday,period_no,start_time,end_time,
                            location,need_num,service_minutes,manager_admin_id) VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,NULL)''',
                            (biz['business_id'],f'{biz["name"]} · 周{"一二三四五六日"[day-1]}第{period}时段',day,period,start,end,biz['name'],duration))
        garden = one(c,"SELECT * FROM business WHERE code='GARDEN'")
        for period, post in enumerate(('A','B'),1):
            if not one(c,'SELECT 1 FROM service_slot WHERE business_id=%s AND period_no=%s',(garden['business_id'],period)):
                c.execute('''INSERT INTO service_slot(business_id,schedule_kind,team_name,period_no,start_time,end_time,
                    location,need_num,service_minutes,manager_admin_id) VALUES(%s,'WEEKLY',%s,%s,NULL,NULL,'开心花园',NULL,90,NULL)''',
                    (garden['business_id'],f'开心花园 {post} 岗',period))
        definitions = {
            'business_member': '''membership_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                business_id BIGINT UNSIGNED NOT NULL, student_id VARCHAR(32) NOT NULL,
                effective_from DATE NOT NULL, effective_until DATE NULL,
                UNIQUE KEY uq_business_member(business_id,student_id,effective_from),
                FOREIGN KEY(business_id) REFERENCES business(business_id), FOREIGN KEY(student_id) REFERENCES student(student_id)''',
            'business_week': '''business_id BIGINT UNSIGNED NOT NULL, semester_id BIGINT UNSIGNED NOT NULL,
                week_no INT NOT NULL, working TINYINT NOT NULL DEFAULT 1, reason VARCHAR(500) NOT NULL,
                admin_id BIGINT UNSIGNED NOT NULL, PRIMARY KEY(business_id,semester_id,week_no),
                FOREIGN KEY(business_id) REFERENCES business(business_id), FOREIGN KEY(semester_id) REFERENCES semester(semester_id)''',
            'membership_change': '''change_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                student_id VARCHAR(32) NOT NULL, effective_date DATE NOT NULL, slot_ids JSON NOT NULL,
                admin_id BIGINT UNSIGNED NOT NULL, reason VARCHAR(500) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'PENDING', FOREIGN KEY(student_id) REFERENCES student(student_id)''',
            'week_suspension': '''schedule_id BIGINT UNSIGNED PRIMARY KEY, snapshot JSON NOT NULL,
                FOREIGN KEY(schedule_id) REFERENCES schedule(schedule_id)''',
            'hour_collection': '''collection_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                business_id BIGINT UNSIGNED NOT NULL, title VARCHAR(100) NOT NULL,
                start_date DATE NOT NULL, end_date DATE NOT NULL, admin_id BIGINT UNSIGNED NOT NULL,
                create_time DATETIME NOT NULL, FOREIGN KEY(business_id) REFERENCES business(business_id)''',
            'collection_item': '''item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                collection_id BIGINT UNSIGNED NOT NULL, title VARCHAR(200) NOT NULL,
                min_minutes INT NOT NULL, max_minutes INT NOT NULL,
                FOREIGN KEY(collection_id) REFERENCES hour_collection(collection_id)''',
            'collection_person': '''collection_id BIGINT UNSIGNED NOT NULL, student_id VARCHAR(32) NOT NULL,
                PRIMARY KEY(collection_id,student_id), FOREIGN KEY(collection_id) REFERENCES hour_collection(collection_id),
                FOREIGN KEY(student_id) REFERENCES student(student_id)''',
            'hour_submission': '''submission_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                item_id BIGINT UNSIGNED NOT NULL, student_id VARCHAR(32) NOT NULL, service_date DATE NOT NULL,
                service_minutes INT NOT NULL, remark VARCHAR(500) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
                rejection_reason VARCHAR(500) NOT NULL DEFAULT '', revision INT NOT NULL DEFAULT 1,
                schedule_id BIGINT UNSIGNED NULL, UNIQUE KEY uq_submission(item_id,student_id,service_date),
                FOREIGN KEY(item_id) REFERENCES collection_item(item_id), FOREIGN KEY(student_id) REFERENCES student(student_id),
                FOREIGN KEY(schedule_id) REFERENCES schedule(schedule_id)''',
            'specialty_import': '''batch_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                business_id BIGINT UNSIGNED NOT NULL, file_hash CHAR(64) NOT NULL, admin_id BIGINT UNSIGNED NOT NULL,
                create_time DATETIME NOT NULL, UNIQUE KEY uq_import_file(business_id,file_hash),
                FOREIGN KEY(business_id) REFERENCES business(business_id)''',
            'specialty_import_row': '''batch_id BIGINT UNSIGNED NOT NULL, row_no INT NOT NULL,
                fingerprint CHAR(64) NOT NULL, schedule_id BIGINT UNSIGNED NOT NULL,
                PRIMARY KEY(batch_id,row_no), INDEX idx_import_fingerprint(fingerprint),
                FOREIGN KEY(batch_id) REFERENCES specialty_import(batch_id), FOREIGN KEY(schedule_id) REFERENCES schedule(schedule_id)''',
            'leave_attachment': '''attachment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                leave_id BIGINT UNSIGNED NOT NULL, mime_type VARCHAR(32) NOT NULL, content MEDIUMBLOB NOT NULL,
                FOREIGN KEY(leave_id) REFERENCES leave_application(leave_id)''',
            'feature_migration': '''name VARCHAR(64) PRIMARY KEY, completed_at DATETIME NOT NULL''',
        }
        for name, body in definitions.items():
            c.execute(f'CREATE TABLE IF NOT EXISTS {name} ({body}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
        if not one(c,"SELECT 1 FROM feature_migration WHERE name='multi_business_v1'"):
            rule = one(c,"SELECT * FROM credit_rule WHERE violation_type='LATE' AND status='ACTIVE'")
            if rule and rule['deduct_score'] != 1:
                c.execute("UPDATE credit_rule SET status='RETIRED' WHERE rule_id=%s",(rule['rule_id'],))
                c.execute("INSERT INTO credit_rule(violation_type,version,deduct_score,create_admin_id) VALUES('LATE',%s,1,%s)",
                          (rule['version']+1,rule['create_admin_id']))
            c.execute("INSERT INTO feature_migration VALUES('multi_business_v1',NOW())")
