from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

FORMAT_VERSION=1
MANIFEST='manifest.json'
DB_MEMBER='database/bosfor.sqlite3'


def _sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def _sha_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def _safe_upload_files(root: Path):
    if not root.exists(): return []
    out=[]
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not p.is_file(): continue
        rel=p.relative_to(root)
        if root.name == 'public' and 'uploads' not in rel.parts: continue
        if any(part in {'.git','private','backups','__pycache__'} for part in rel.parts): continue
        if p.name.lower() in {'.env','admin-password.txt'}: continue
        out.append((p,rel))
    return out


def create_backup(db_path: Path|str, uploads_dir: Path|str, destination: Path|str) -> dict:
    db_path=Path(db_path); uploads_dir=Path(uploads_dir); destination=Path(destination)
    if not db_path.is_file(): raise FileNotFoundError(db_path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bosfor-backup-') as td:
        snap=Path(td)/'bosfor.sqlite3'
        src=sqlite3.connect(str(db_path),timeout=15); dst=sqlite3.connect(str(snap))
        try:
            with dst: src.backup(dst)
        finally: src.close();dst.close()
        check=sqlite3.connect(str(snap)); integrity=check.execute('PRAGMA integrity_check').fetchone()[0]; fks=check.execute('PRAGMA foreign_key_check').fetchall();check.close()
        if integrity!='ok' or fks: raise RuntimeError('database integrity check failed before backup')
        assets=[]
        for p,rel in _safe_upload_files(uploads_dir):
            assets.append({'path':f'uploads/{rel.as_posix()}','sha256':_sha(p),'size':p.stat().st_size})
        manifest={'format_version':FORMAT_VERSION,'created_at':int(time.time()*1000),'database':{'path':DB_MEMBER,'sha256':_sha(snap),'size':snap.stat().st_size},'assets':assets}
        tmp=destination.with_suffix(destination.suffix+'.tmp')
        if tmp.exists(): tmp.unlink()
        try:
            with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                z.write(snap,DB_MEMBER)
                for p,rel in _safe_upload_files(uploads_dir): z.write(p,f'uploads/{rel.as_posix()}')
                z.writestr(MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True))
            os.replace(tmp,destination)
        finally:
            if tmp.exists(): tmp.unlink()
    return manifest


def _valid_member(name: str) -> bool:
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name


def verify_backup(path: Path|str) -> dict:
    path=Path(path); errors=[]
    try:
        with zipfile.ZipFile(path) as z:
            names=set(z.namelist())
            if MANIFEST not in names: return {'ok':False,'checksum_errors':['manifest missing'],'integrity':'unknown','foreign_key_violations':-1}
            manifest=json.loads(z.read(MANIFEST))
            if manifest.get('format_version')!=FORMAT_VERSION: errors.append('unsupported format')
            expected=[manifest.get('database',{})]+list(manifest.get('assets',[]))
            for item in expected:
                name=str(item.get('path',''))
                if not _valid_member(name) or name not in names: errors.append(f'missing/unsafe:{name}');continue
                if _sha_bytes(z.read(name))!=item.get('sha256'): errors.append(f'checksum:{name}')
            if any(not _valid_member(n) for n in names): errors.append('unsafe archive member')
            db_bytes=z.read(DB_MEMBER) if DB_MEMBER in names else b''
        integrity='unknown';fk_count=-1
        if db_bytes:
            with tempfile.TemporaryDirectory(prefix='bosfor-verify-') as td:
                db=Path(td)/'db.sqlite3';db.write_bytes(db_bytes);c=sqlite3.connect(str(db));integrity=c.execute('PRAGMA integrity_check').fetchone()[0];fk_count=len(c.execute('PRAGMA foreign_key_check').fetchall());c.close()
                if integrity!='ok': errors.append('database integrity')
                if fk_count: errors.append('foreign keys')
        return {'ok':not errors,'checksum_errors':errors,'integrity':integrity,'foreign_key_violations':fk_count,'manifest':manifest}
    except (OSError,zipfile.BadZipFile,json.JSONDecodeError,KeyError) as exc:
        return {'ok':False,'checksum_errors':[str(exc)],'integrity':'unknown','foreign_key_violations':-1}


def restore_to_new_location(path: Path|str, destination: Path|str) -> dict:
    path=Path(path); destination=Path(destination)
    result=verify_backup(path)
    if not result['ok']: raise ValueError('backup verification failed')
    if destination.exists() and any(destination.iterdir()): raise FileExistsError('restore destination must be empty')
    destination.mkdir(parents=True,exist_ok=True)
    manifest=result['manifest']; allowed={MANIFEST,manifest['database']['path']}|{x['path'] for x in manifest.get('assets',[])}
    with zipfile.ZipFile(path) as z:
        for name in allowed:
            if name==MANIFEST or name not in z.namelist(): continue
            if not _valid_member(name): raise ValueError('unsafe backup member')
            target=destination.joinpath(*PurePosixPath(name).parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    return {'ok':True,'destination':str(destination),'database':str(destination/DB_MEMBER),'asset_count':len(manifest.get('assets',[]))}
