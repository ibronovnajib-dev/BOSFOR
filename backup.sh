#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
NAME="${1:-$(date +%Y-%m-%d_%H-%M-%S)}"
DEST="private/backups/${NAME}.zip"
mkdir -p private/backups
python3 - "$DEST" <<'PY'
from pathlib import Path
import sys
from bosfor.backup import create_backup,verify_backup
out=Path(sys.argv[1])
manifest=create_backup(Path('private/bosfor.sqlite3'),Path('public'),out)
check=verify_backup(out)
if not check['ok']:
    raise SystemExit('Backup verification failed: '+repr(check))
print(f"Backup created and verified: {out}")
print(f"Database SHA-256: {manifest['database']['sha256']}")
print(f"Uploaded assets: {len(manifest['assets'])}")
PY
