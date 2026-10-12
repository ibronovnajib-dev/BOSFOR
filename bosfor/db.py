from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    con=sqlite3.connect(str(db_path),timeout=15,isolation_level=None)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=15000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    return con

@contextmanager
def transaction(con: sqlite3.Connection):
    began=not con.in_transaction
    try:
        if began: con.execute('BEGIN IMMEDIATE')
        yield con
        if began: con.commit()
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise
