"""Add business lifecycle and groups without rewriting accounting history."""
from .db import Database,one

GROUPS=['综合运营中心','图志之家','活动策划中心','物资采购中心','宣传推广中心','音视频制作中心','摄影摄像中心','青广干事']

def installed(c):
    c.execute("SHOW TABLES LIKE 'business_window'")
    return bool(c.fetchone())

def migrate(settings):
    with Database(settings).transaction() as c:
        ready=one(c,"SELECT 1 FROM feature_migration WHERE name='business_directory_v1'")
    if not ready and settings.get('database')=='volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        for table,fields in {'business':{'status':"VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'",'revision':'INT NOT NULL DEFAULT 1'},
                             'hour_collection':{'group_id':'BIGINT UNSIGNED NULL'},'schedule':{'group_id':'BIGINT UNSIGNED NULL'},
                             'collection_scope_request':{'group_id':'BIGINT UNSIGNED NULL'}}.items():
            for col,definition in fields.items():
                c.execute(f'SHOW COLUMNS FROM {table} LIKE %s',(col,))
                if not c.fetchone():c.execute(f'ALTER TABLE {table} ADD {col} {definition}')
        definitions={
          'business_window':'''window_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,business_id BIGINT UNSIGNED NOT NULL,
            active_from DATETIME NOT NULL,active_until DATETIME NULL,FOREIGN KEY(business_id) REFERENCES business(business_id)''',
          'business_group':'''group_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,business_id BIGINT UNSIGNED NOT NULL,
            name VARCHAR(100) NOT NULL,UNIQUE KEY uq_business_group(business_id,name),FOREIGN KEY(business_id) REFERENCES business(business_id)''',
          'group_member':'''membership_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,group_id BIGINT UNSIGNED NOT NULL,
            student_id VARCHAR(32) NOT NULL,effective_from DATE NOT NULL,effective_until DATE NULL,
            UNIQUE KEY uq_group_member(group_id,student_id,effective_from),FOREIGN KEY(group_id) REFERENCES business_group(group_id),
            FOREIGN KEY(student_id) REFERENCES student(student_id)''',
          'collection_group_manager':'''admin_id BIGINT UNSIGNED NOT NULL,group_id BIGINT UNSIGNED NOT NULL,
            assigned_by BIGINT UNSIGNED NOT NULL,assigned_at DATETIME NOT NULL,PRIMARY KEY(admin_id,group_id),
            FOREIGN KEY(admin_id) REFERENCES admin(admin_id),FOREIGN KEY(group_id) REFERENCES business_group(group_id)''',
          'member_import':'''batch_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,file_hash CHAR(64) NOT NULL,
            request_hash CHAR(64) NOT NULL UNIQUE,admin_id BIGINT UNSIGNED NOT NULL,created_at DATETIME NOT NULL''',
          'member_import_row':'''batch_id BIGINT UNSIGNED NOT NULL,sheet_name VARCHAR(100) NOT NULL,row_no INT NOT NULL,
            student_id VARCHAR(32) NOT NULL,business_id BIGINT UNSIGNED NOT NULL,group_id BIGINT UNSIGNED NULL,
            PRIMARY KEY(batch_id,sheet_name,row_no),FOREIGN KEY(batch_id) REFERENCES member_import(batch_id)'''}
        for table,body in definitions.items():c.execute(f'CREATE TABLE IF NOT EXISTS {table} ({body}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
        c.execute("INSERT INTO business_window(business_id,active_from) SELECT b.business_id,'1900-01-01' FROM business b WHERE NOT EXISTS(SELECT 1 FROM business_window w WHERE w.business_id=b.business_id)")
        old=one(c,"SELECT * FROM business WHERE name='干部'");new=one(c,"SELECT * FROM business WHERE name='干部及干事'")
        if old and not new:
            c.execute("UPDATE business SET name='干部及干事' WHERE business_id=%s",(old['business_id'],));new=old
        if old and new and old['business_id']!=new['business_id']:raise RuntimeError('干部业务名称冲突，需先核对，不能自动合并')
        if new:
            for name in GROUPS:c.execute('INSERT IGNORE INTO business_group(business_id,name) VALUES(%s,%s)',(new['business_id'],name))
        c.execute("INSERT IGNORE INTO feature_migration VALUES('business_directory_v1',NOW())")
