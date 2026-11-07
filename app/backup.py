"""Consistent logical backup before a production schema upgrade.

Works for both deployments:
* private instance: uses the ``mysqldump`` next to the binary recorded in
  ``.work/mysql-core/server.json``;
* external MySQL (``VOLUNTEER_DB_CONFIG``): falls back to ``mysqldump`` found on
  ``PATH`` and skips the backup with an explicit warning if none is available,
  so bootstrapping an external database never fails just because this machine
  has no local private instance.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from .paths import BACKUP_ROOT, SERVER_CONFIG

DUMP_NAME = 'mysqldump.exe' if os.name == 'nt' else 'mysqldump'


def dump_binary():
    """Locate a mysqldump binary: private instance first, then PATH."""
    if SERVER_CONFIG.is_file():
        try:
            # utf-8-sig tolerates a BOM added by Windows editors/Set-Content.
            metadata = json.loads(SERVER_CONFIG.read_text(encoding='utf-8-sig'))
            candidate = Path(metadata['bin']) / DUMP_NAME
            if candidate.is_file():
                return candidate
        except (OSError, KeyError, TypeError, ValueError):
            pass
    found = shutil.which('mysqldump')
    return Path(found) if found else None


def backup_database(settings):
    database=settings.get('database','volunteer_core')
    if database=='volunteer_core_test':return None
    if database!='volunteer_core':raise RuntimeError('拒绝备份未知数据库')
    binary=dump_binary()
    if binary is None:
        print('警告：未找到 mysqldump，已跳过升级前数据库备份。'
              '请安装 MySQL 客户端工具或把 mysqldump 加入 PATH 后重新执行；'
              '若无法备份，请先手动备份外部数据库再升级。', file=sys.stderr, flush=True)
        return None
    folder=BACKUP_ROOT;folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
    output=folder/f'volunteer_core-before-business-{stamp}.sql'
    # ASCII file name next to an ASCII working directory: MySQL clients on
    # Windows handle relative option-file names more reliably than CJK paths.
    option_file=folder/f'backup-{stamp}.cnf'
    def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'
    options={'user':settings['user'],'password':settings['password'],
             'host':settings.get('host','127.0.0.1'),'port':settings.get('port',3306),'protocol':'tcp'}
    option_file.write_text('[client]\n'+'\n'.join(k+'='+quoted(v) for k,v in options.items())+'\n',encoding='utf-8')
    try:
        with output.open('wb') as target:
            result=subprocess.run([str(binary),'--defaults-file='+option_file.name,'--single-transaction','--routines','--triggers',
                '--hex-blob','--default-character-set=utf8mb4',database],stdout=target,stderr=subprocess.PIPE,
                cwd=option_file.parent,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180)
        if result.returncode or output.stat().st_size<100:
            raise RuntimeError('升级前备份未成功，已停止数据库迁移；请检查本机 MySQL 工具')
        # Image evidence is stored in leave_attachment and included as hex BLOB data.
        return str(output)
    finally:option_file.unlink(missing_ok=True)
