"""Add collection delegation, two-stage review, submission files and inboxes."""
from .db import Database, one


def installed(c):
    c.execute("SHOW TABLES LIKE 'inbox_notice'")
    return bool(c.fetchone())


def migrate(settings):
    marker='collection_governance_v1'
    with Database(settings).transaction() as c:
        ready=bool(one(c,'SELECT 1 FROM feature_migration WHERE name=%s',(marker,)))
    if not ready and settings.get('database')=='volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        columns={'hour_collection':{
            'submission_deadline':'DATE NULL','status':"VARCHAR(16) NOT NULL DEFAULT 'OPEN'",
            'closed_at':'DATETIME NULL','close_reason':"VARCHAR(500) NOT NULL DEFAULT ''"},
            'hour_submission':{'attachment_revision':'INT NOT NULL DEFAULT 0',
                               'first_admin_id':'BIGINT UNSIGNED NULL','final_admin_id':'BIGINT UNSIGNED NULL'}}
        for table,fields in columns.items():
            for name,definition in fields.items():
                c.execute(f"SHOW COLUMNS FROM {table} LIKE %s",(name,))
                if not c.fetchone():c.execute(f'ALTER TABLE {table} ADD {name} {definition}')
        definitions={
            'collection_manager':'''admin_id BIGINT UNSIGNED NOT NULL,business_id BIGINT UNSIGNED NOT NULL,
                assigned_by BIGINT UNSIGNED NOT NULL,assigned_at DATETIME NOT NULL,
                PRIMARY KEY(admin_id,business_id),FOREIGN KEY(admin_id) REFERENCES admin(admin_id),
                FOREIGN KEY(business_id) REFERENCES business(business_id)''',
            'collection_scope_request':'''request_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                admin_id BIGINT UNSIGNED NOT NULL,business_id BIGINT UNSIGNED NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'PENDING',reason VARCHAR(500) NOT NULL,
                review_reason VARCHAR(500) NOT NULL DEFAULT '',review_admin_id BIGINT UNSIGNED NULL,
                revision INT NOT NULL DEFAULT 1,created_at DATETIME NOT NULL,reviewed_at DATETIME NULL,
                FOREIGN KEY(admin_id) REFERENCES admin(admin_id),FOREIGN KEY(business_id) REFERENCES business(business_id)''',
            'submission_attachment':'''attachment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                submission_id BIGINT UNSIGNED NOT NULL,submission_revision INT NOT NULL,
                filename VARCHAR(200) NOT NULL,mime_type VARCHAR(100) NOT NULL,size_bytes INT UNSIGNED NOT NULL,
                content MEDIUMBLOB NOT NULL,FOREIGN KEY(submission_id) REFERENCES hour_submission(submission_id)''',
            'submission_review':'''review_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                submission_id BIGINT UNSIGNED NOT NULL,revision INT NOT NULL,stage VARCHAR(16) NOT NULL,
                admin_id BIGINT UNSIGNED NOT NULL,approved TINYINT NOT NULL,service_minutes INT NOT NULL,
                reason VARCHAR(500) NOT NULL,created_at DATETIME NOT NULL,
                UNIQUE KEY uq_submission_review(submission_id,revision),FOREIGN KEY(submission_id) REFERENCES hour_submission(submission_id)''',
            'inbox_notice':'''notice_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                recipient_kind VARCHAR(16) NOT NULL,recipient_id VARCHAR(32) NOT NULL,
                event_key VARCHAR(180) NOT NULL,category VARCHAR(30) NOT NULL,title VARCHAR(100) NOT NULL,
                message VARCHAR(1000) NOT NULL,target_page VARCHAR(40) NOT NULL,target_id VARCHAR(64) NULL,
                created_at DATETIME NOT NULL,read_at DATETIME NULL,
                UNIQUE KEY uq_inbox_event(recipient_kind,recipient_id,event_key),
                INDEX idx_inbox_recipient(recipient_kind,recipient_id,notice_id)'''}
        for name,body in definitions.items():
            c.execute(f'CREATE TABLE IF NOT EXISTS {name} ({body}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
        c.execute('INSERT IGNORE INTO feature_migration(name,completed_at) VALUES(%s,NOW())',(marker,))
