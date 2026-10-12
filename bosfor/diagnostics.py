from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import connect
from .migrations import current_schema_version


def _writable(path: Path) -> bool:
    target=path if path.exists() else path.parent
    return target.exists() and os.access(target,os.W_OK)


def diagnose(db_path: Path|str, public_dir: Path|str, private_dir: Path|str) -> dict:
    db_path=Path(db_path); public_dir=Path(public_dir); private_dir=Path(private_dir)
    db_info={'exists':db_path.is_file(),'integrity':'unavailable','foreign_key_violations':-1,'journal_mode':'unknown','schema_version':0}
    db_ok=False
    if db_path.is_file():
        try:
            con=connect(db_path)
            try:
                db_info.update(
                    integrity=con.execute('PRAGMA integrity_check').fetchone()[0],
                    foreign_key_violations=len(con.execute('PRAGMA foreign_key_check').fetchall()),
                    journal_mode=str(con.execute('PRAGMA journal_mode').fetchone()[0]),
                    schema_version=current_schema_version(con),
                )
                db_ok=db_info['integrity']=='ok' and db_info['foreign_key_violations']==0
            finally: con.close()
        except sqlite3.Error:
            db_ok=False
    upload_candidates=[public_dir/'img'/'uploads',public_dir/'icons'/'uploads']
    uploads_writable=all(_writable(p) for p in upload_candidates)
    backups=private_dir/'backups'; zips=[]
    if backups.is_dir():
        try:zips=[p for p in backups.glob('*.zip') if p.is_file()]
        except OSError:zips=[]
    newest=max((p.stat().st_mtime for p in zips),default=None)
    backup={'exists':bool(newest),'age_seconds':None if newest is None else max(0,int(time.time()-newest))}
    try: ZoneInfo('Asia/Dushanbe'); tz_ok=True
    except Exception: tz_ok=False
    assets={
        'index_html':(public_dir/'index.html').is_file(),
        'admin_html':(public_dir/'admin.html').is_file(),
        'manifest':(public_dir/'manifest.webmanifest').is_file(),
    }
    storage={'private_writable':_writable(private_dir),'uploads_writable':uploads_writable,'backup_dir_writable':_writable(backups)}
    required_assets=assets['index_html'] and assets['admin_html']
    ok=db_ok and storage['private_writable'] and uploads_writable and required_assets and tz_ok
    return {'ok':ok,'database':db_info,'storage':storage,'assets':assets,'backup':backup,'timezone':{'name':'Asia/Dushanbe','available':tz_ok}}
