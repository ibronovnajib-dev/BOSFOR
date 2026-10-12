from __future__ import annotations

import sqlite3
import time
from typing import Any

from .migrations import ensure_phase2_schema
from .orders import OrderConflict, create_pos_order, recalculate_order


class FloorConflict(RuntimeError):
    pass


STATE_GRAPH = {
    'free': {'reserved','seated','out_of_service'},
    'reserved': {'seated','free','out_of_service'},
    'seated': {'ordering','out_of_service'},
    'ordering': {'preparing','eating','bill','out_of_service'},
    'preparing': {'eating','bill','out_of_service'},
    'eating': {'bill','out_of_service'},
    'bill': {'cleaning','out_of_service'},
    'cleaning': {'free','out_of_service'},
    'out_of_service': {'free'},
}


def _now(): return int(time.time()*1000)

def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')


def _ensure_table_row(con: sqlite3.Connection, table_id: str) -> None:
    table=con.execute('SELECT code,active FROM tables_map WHERE code=?',(table_id,)).fetchone()
    if not table or not int(table['active']): raise FloorConflict('table unavailable')
    con.execute('''INSERT OR IGNORE INTO os_table_state(table_id,state,version,updated_at)
                   VALUES(?, 'free', 1, ?)''',(table_id,_now()))


def _table_state(con, table_id):
    _ensure_table_row(con,table_id)
    r=con.execute('SELECT * FROM os_table_state WHERE table_id=?',(table_id,)).fetchone()
    return dict(r)


def seat_table(con: sqlite3.Connection, table_id: str, actor: dict, reservation_id: str | None = None) -> dict:
    ensure_phase2_schema(con)
    began=False
    try:
        if not con.in_transaction:
            con.execute('BEGIN IMMEDIATE'); began=True
        _ensure_table_row(con,table_id)
        current=con.execute('SELECT state,active_order_id FROM os_table_state WHERE table_id=?',(table_id,)).fetchone()
        if current['state'] not in {'free','reserved'} or current['active_order_id']:
            raise FloorConflict('table already occupied')
        if current['state']=='reserved' and not reservation_id:
            raise FloorConflict('table reserved')
        order=create_pos_order(con,actor,'pos_dinein',table_id)
        cur=con.execute('''INSERT INTO os_seatings(table_id,order_id,reservation_id,actor_id,seated_at)
                           VALUES(?,?,?,?,?)''',(table_id,order['id'],reservation_id,_actor_id(actor),_now()))
        changed=con.execute('''UPDATE os_table_state SET state='seated',version=version+1,active_order_id=?,seating_id=?,updated_at=?
                               WHERE table_id=? AND state IN ('free','reserved') AND active_order_id IS NULL''',
                            (order['id'],cur.lastrowid,_now(),table_id)).rowcount
        if changed != 1: raise FloorConflict('table seat conflict')
        if began: con.commit()
        r=con.execute('SELECT * FROM os_seatings WHERE id=?',(cur.lastrowid,)).fetchone()
        return dict(r)
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise FloorConflict('table busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def set_table_state(con: sqlite3.Connection, table_id: str, target: str, actor: dict) -> dict:
    ensure_phase2_schema(con); current=_table_state(con,table_id)
    if target==current['state']: return current
    if target not in STATE_GRAPH.get(current['state'],set()): raise FloorConflict(f"invalid table transition {current['state']}->{target}")
    if target=='free' and current.get('active_order_id'):
        raise FloorConflict('cannot free table with active order')
    con.execute('UPDATE os_table_state SET state=?,version=version+1,updated_at=? WHERE table_id=?',(target,_now(),table_id))
    return _table_state(con,table_id)


def _release_table(con, table_id, order_id):
    if not table_id: return
    _ensure_table_row(con,table_id)
    con.execute('''UPDATE os_table_state SET state='free',active_order_id=NULL,seating_id=NULL,version=version+1,updated_at=?
                   WHERE table_id=? AND active_order_id=?''',(_now(),table_id,order_id))
    con.execute('UPDATE os_seatings SET ended_at=? WHERE table_id=? AND order_id=? AND ended_at IS NULL',(_now(),table_id,order_id))


def move_order(con: sqlite3.Connection, order_id: str, to_table_id: str, actor: dict) -> dict:
    ensure_phase2_schema(con); began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        order=con.execute('SELECT * FROM os_orders WHERE id=?',(order_id,)).fetchone()
        if not order or order['state'] in {'closed','cancelled'}: raise FloorConflict('order not movable')
        from_table=order['table_id']
        _ensure_table_row(con,to_table_id)
        target=con.execute('SELECT state,active_order_id FROM os_table_state WHERE table_id=?',(to_table_id,)).fetchone()
        if target['state']!='free' or target['active_order_id']: raise FloorConflict('target table occupied')
        if from_table: _release_table(con,from_table,order_id)
        con.execute('UPDATE os_orders SET table_id=?,version=version+1 WHERE id=?',(to_table_id,order_id))
        con.execute('UPDATE os_seatings SET ended_at=? WHERE order_id=? AND ended_at IS NULL',(_now(),order_id))
        cur=con.execute('INSERT INTO os_seatings(table_id,order_id,actor_id,seated_at) VALUES(?,?,?,?)',(to_table_id,order_id,_actor_id(actor),_now()))
        con.execute("UPDATE os_table_state SET state='seated',active_order_id=?,seating_id=?,version=version+1,updated_at=? WHERE table_id=?",(order_id,cur.lastrowid,_now(),to_table_id))
        if began: con.commit()
        return dict(con.execute('SELECT * FROM os_orders WHERE id=?',(order_id,)).fetchone())
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def merge_orders(con: sqlite3.Connection, source_id: str, target_id: str, actor: dict) -> dict:
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise FloorConflict('permission denied')
    if source_id==target_id: raise FloorConflict('cannot merge same order')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        source=con.execute('SELECT * FROM os_orders WHERE id=?',(source_id,)).fetchone(); target=con.execute('SELECT * FROM os_orders WHERE id=?',(target_id,)).fetchone()
        if not source or not target: raise FloorConflict('order not found')
        if source['state'] in {'closed','cancelled'} or target['state'] in {'closed','cancelled'}: raise FloorConflict('order not mergeable')
        # Sent kitchen lines cannot be silently reassigned after routing.
        sent=con.execute('SELECT COUNT(*) c FROM os_order_items WHERE order_id=? AND sent_qty>0',(source_id,)).fetchone()['c']
        if sent: raise FloorConflict('source has sent kitchen items')
        con.execute('UPDATE os_order_items SET order_id=? WHERE order_id=?',(target_id,source_id))
        con.execute('UPDATE os_order_adjustments SET order_id=? WHERE order_id=?',(target_id,source_id))
        con.execute('UPDATE os_payments SET order_id=? WHERE order_id=?',(target_id,source_id))
        recalculate_order(con,target_id)
        source_table=source['table_id']
        if source_table: _release_table(con,source_table,source_id)
        con.execute("UPDATE os_orders SET state='cancelled',version=version+1 WHERE id=?",(source_id,))
        if began: con.commit()
        return dict(con.execute('SELECT * FROM os_orders WHERE id=?',(target_id,)).fetchone())
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise
