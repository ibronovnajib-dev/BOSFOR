from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path

ALLOWED_TOP_FILES={
    'server.py','requirements.txt','requirements-dev.txt','README_PRODUCTION.md','backup.sh',
    'robots.txt','sitemap.xml','.gitignore','build_release.py'
}
ALLOWED_DIRS={'public','bosfor','docs'}
EXCLUDED_PARTS={'.git','.worktrees','private','tests','__pycache__','.pytest_cache','.superpowers','backups','.venv','venv','node_modules'}
EXCLUDED_NAMES={'.env','admin-password.txt','.DS_Store'}
EXCLUDED_SUFFIXES={'.pyc','.pyo','.sqlite','.sqlite3','.db','.log','.tmp'}


def _allowed(root: Path,p: Path)->bool:
    rel=p.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts): return False
    if p.name in EXCLUDED_NAMES or p.suffix.lower() in EXCLUDED_SUFFIXES: return False
    if len(rel.parts)==1:return p.name in ALLOWED_TOP_FILES
    return rel.parts[0] in ALLOWED_DIRS


def _sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def build_release(source_root: Path|str,destination: Path|str)->dict:
    root=Path(source_root).resolve();destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    files=[p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and _allowed(root,p)]
    if not any(p.relative_to(root).as_posix()=='server.py' for p in files): raise ValueError('server.py missing')
    if not any(p.relative_to(root).as_posix()=='public/index.html' for p in files): raise ValueError('public/index.html missing')
    file_manifest=[{'path':p.relative_to(root).as_posix(),'sha256':_sha_file(p),'size':p.stat().st_size} for p in files]
    meta={'format':'bosfor-release-v1','created_at':int(time.time()*1000),'file_count':len(files),'files':file_manifest}
    tmp=destination.with_suffix(destination.suffix+'.tmp')
    if tmp.exists():tmp.unlink()
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in files:z.write(p,p.relative_to(root).as_posix())
            z.writestr('RELEASE_MANIFEST.json',json.dumps(meta,ensure_ascii=False,indent=2,sort_keys=True))
        os.replace(tmp,destination)
    finally:
        if tmp.exists():tmp.unlink()
    meta['sha256']=_sha_file(destination)
    meta['archive']=destination.name
    return meta
