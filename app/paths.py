"""Single source of truth for the project's filesystem layout.

The defaults preserve the historical layout so existing databases keep working:
runtime data (MySQL files, credentials, backups, signed-session secret) lives in
``<repository parent>/.work``.  Nothing here imports third-party packages, so the
module also works for a bare Python that only needs to locate files.

Environment variables (read once at import time):
  VOLUNTEER_HOME  runtime data root; replaces the default ``.work`` directory.
                  MySQL state then lives in ``$VOLUNTEER_HOME/mysql-core``.
  VOLUNTEER_DB_CONFIG  explicit database JSON config (used by app.db).
"""
from __future__ import annotations

import os
from pathlib import Path

#: The project directory that contains this package (``2026database``).
CORE = Path(__file__).resolve().parents[1]
#: Historical workspace root: the directory that contains the project.
WORKSPACE = CORE.parent
#: Legacy alias kept for callers that imported ``app.db.ROOT``.
ROOT = WORKSPACE


def _data_root() -> Path:
    override = os.environ.get("VOLUNTEER_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return WORKSPACE / ".work"


#: Runtime data root (default: sibling ``.work`` of the repository).
DATA_ROOT = _data_root()
#: Private MySQL instance directory inside the data root.
MYSQL_STATE = DATA_ROOT / "mysql-core"
MYSQL_DATA = MYSQL_STATE / "data"
MYSQL_CNF = MYSQL_STATE / "my.cnf"
SERVER_CONFIG = MYSQL_STATE / "server.json"
ADMIN_CONFIG = MYSQL_STATE / "admin.json"
RUNTIME_CONFIG = MYSQL_STATE / "runtime.json"
#: Demo accounts written by ``python -m app.bootstrap`` on first initialization.
DEMO_ACCOUNTS = DATA_ROOT / "demo-accounts.json"
#: Local signing key for API sessions.
TOKEN_SECRET = DATA_ROOT / "token-secret"
#: Directory for mysqldump backups taken before schema migrations.
BACKUP_ROOT = DATA_ROOT / "backups"

#: Source assets shipped with the project.
WEB_ROOT = CORE / "web"
TEMPLATES_ROOT = CORE / "templates"
SQL_ROOT = CORE / "sql"

#: Database config used by ``app.db.Database()`` when nothing is passed.
DB_CONFIG = Path(os.environ["VOLUNTEER_DB_CONFIG"]).expanduser() if os.environ.get(
    "VOLUNTEER_DB_CONFIG", "").strip() else RUNTIME_CONFIG
