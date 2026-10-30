"""Add collection files without changing existing collections or ledgers."""
from .db import Database, one


def migrate(settings):
    marker='collection_attachments_v1'
    with Database(settings).transaction() as c:
        ready=bool(one(c,'SELECT 1 FROM feature_migration WHERE name=%s',(marker,)))
    if not ready and settings.get('database')=='volunteer_core':
        from .backup import backup_database
        backup_database(settings)
    with Database(settings).transaction(True) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS collection_attachment (
            attachment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            collection_id BIGINT UNSIGNED NOT NULL, filename VARCHAR(200) NOT NULL,
            mime_type VARCHAR(100) NOT NULL, size_bytes INT UNSIGNED NOT NULL,
            content MEDIUMBLOB NOT NULL,
            FOREIGN KEY(collection_id) REFERENCES hour_collection(collection_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        c.execute('INSERT IGNORE INTO feature_migration(name,completed_at) VALUES(%s,NOW())',(marker,))
