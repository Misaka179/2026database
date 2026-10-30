"""Consistent logical backup before a production schema upgrade."""
import json
import os
from pathlib import Path
import secrets
import subprocess
from datetime import datetime
from .db import ROOT


def backup_database(settings):
    database=settings.get('database','volunteer_core')
    if database=='volunteer_core_test':return None
    if database!='volunteer_core':raise RuntimeError('拒绝备份未知数据库')
    metadata=json.loads((ROOT/'.work/mysql-core/server.json').read_text(encoding='utf-8'))
    binary=Path(metadata['bin'])/('mysqldump.exe' if os.name=='nt' else 'mysqldump')
    folder=ROOT/'.work/backups';folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
    output=folder/f'volunteer_core-before-business-{stamp}.sql'
    option_file=ROOT/'.work/mysql-core'/f'backup-{stamp}.cnf'
    def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'
    options={'user':settings['user'],'password':settings['password'],'host':settings['host'],'port':settings['port'],'protocol':'tcp'}
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
