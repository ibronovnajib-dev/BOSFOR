from __future__ import annotations

import secrets
import sqlite3
import time

from .migrations import ensure_phase2_schema, ensure_phase4_schema
from .tables import FloorConflict, seat_table


class ReservationConflict(RuntimeError):
    pass


def _now() -> int:
    return int(time.time() * 1000)


def _actor_id(actor: dict) -> str:
    return str(actor.get('id') or actor.get('username') or 'system')


def _need(actor: dict, roles={'owner','manager','waiter'}):
    if actor.get('role') not in roles:
        raise ReservationConflict('permission denied')


def _booking(con: sqlite3.Connection, reservation_id: str):
    row=con.execute('SELECT * FROM bookings WHERE id=?',(reservation_id,)).fetchone()
    if not row:
        raise ReservationConflict('reservation not found')
    return dict(row)


def _release_reserved_table(con: sqlite3.Connection, reservation_id: str) -> None:
    link=con.execute('SELECT * FROM os_reservation_tables WHERE reservation_id=?',(reservation_id,)).fetchone()
    if not link or link['released_at'] is not None:
        return
    con.execute("""UPDATE os_table_state SET state='free',version=version+1,updated_at=?
                   WHERE table_id=? AND state='reserved' AND active_order_id IS NULL""",(_now(),link['table_id']))
    con.execute('UPDATE os_reservation_tables SET released_at=? WHERE reservation_id=?',(_now(),reservation_id))


def assign_reservation_table(con: sqlite3.Connection, reservation_id: str, table_id: str, actor: dict) -> dict:
    ensure_phase2_schema(con); ensure_phase4_schema(con); _need(actor)
    began=False
    try:
        if not con.in_transaction:
            con.execute('BEGIN IMMEDIATE'); began=True
        booking=_booking(con,reservation_id)
        if booking['status'] in {'cancelled','no_show','seated'}:
            raise ReservationConflict('reservation not assignable')
        try: guests=int(booking['guests'])
        except Exception: raise ReservationConflict('invalid guest count')
        table=con.execute('SELECT code,capacity,active FROM tables_map WHERE code=?',(table_id,)).fetchone()
        if not table or not int(table['active']): raise ReservationConflict('table unavailable')
        if int(table['capacity']) < guests: raise ReservationConflict('table capacity too small')
        con.execute("INSERT OR IGNORE INTO os_table_state(table_id,state,version,updated_at) VALUES(?,'free',1,?)",(table_id,_now()))
        existing=con.execute('SELECT reservation_id FROM os_reservation_tables WHERE table_id=? AND released_at IS NULL',(table_id,)).fetchone()
        if existing and existing['reservation_id'] != reservation_id:
            raise ReservationConflict('table already reserved')
        state=con.execute('SELECT state,active_order_id FROM os_table_state WHERE table_id=?',(table_id,)).fetchone()
        if state['active_order_id'] or state['state'] not in {'free','reserved'}:
            raise ReservationConflict('table unavailable')
        old=con.execute('SELECT table_id,released_at FROM os_reservation_tables WHERE reservation_id=?',(reservation_id,)).fetchone()
        if old and old['released_at'] is None and old['table_id'] != table_id:
            _release_reserved_table(con,reservation_id)
        con.execute('''INSERT INTO os_reservation_tables(reservation_id,table_id,assigned_by,assigned_at,released_at)
                       VALUES(?,?,?,?,NULL)
                       ON CONFLICT(reservation_id) DO UPDATE SET table_id=excluded.table_id,assigned_by=excluded.assigned_by,assigned_at=excluded.assigned_at,released_at=NULL,seated_order_id=NULL''',
                    (reservation_id,table_id,_actor_id(actor),_now()))
        con.execute("UPDATE os_table_state SET state='reserved',version=version+1,updated_at=? WHERE table_id=? AND active_order_id IS NULL",(_now(),table_id))
        con.execute("UPDATE bookings SET status=CASE WHEN status='new' THEN 'confirmed' ELSE status END WHERE id=?",(reservation_id,))
        if began: con.commit()
        row=con.execute('SELECT * FROM os_reservation_tables WHERE reservation_id=?',(reservation_id,)).fetchone()
        return dict(row)
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise ReservationConflict('reservation busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def cancel_reservation(con: sqlite3.Connection, reservation_id: str, actor: dict, reason: str) -> dict:
    ensure_phase4_schema(con); _need(actor,{'owner','manager','waiter'})
    if len(str(reason or '').strip()) < 2: raise ReservationConflict('reason required')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        booking=_booking(con,reservation_id)
        if booking['status']=='seated': raise ReservationConflict('seated reservation cannot be cancelled here')
        _release_reserved_table(con,reservation_id)
        con.execute("UPDATE bookings SET status='cancelled',note=CASE WHEN note='' THEN ? ELSE note||' | '||? END WHERE id=?",(str(reason).strip(),str(reason).strip(),reservation_id))
        if began: con.commit()
        return _booking(con,reservation_id)
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def mark_no_show(con: sqlite3.Connection, reservation_id: str, actor: dict, reason: str) -> dict:
    ensure_phase4_schema(con); _need(actor,{'owner','manager','waiter'})
    if len(str(reason or '').strip()) < 2: raise ReservationConflict('reason required')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        booking=_booking(con,reservation_id)
        if booking['status']=='seated': raise ReservationConflict('seated reservation cannot be no-show')
        _release_reserved_table(con,reservation_id)
        con.execute("UPDATE bookings SET status='no_show',note=CASE WHEN note='' THEN ? ELSE note||' | '||? END WHERE id=?",(str(reason).strip(),str(reason).strip(),reservation_id))
        if began: con.commit()
        return _booking(con,reservation_id)
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def quote_wait(con: sqlite3.Connection, guests: int) -> dict:
    ensure_phase2_schema(con); ensure_phase4_schema(con)
    try: guests=int(guests)
    except Exception: raise ReservationConflict('invalid guest count')
    if guests < 1 or guests > 50: raise ReservationConflict('invalid guest count')
    table=con.execute('''SELECT t.code FROM tables_map t
                         LEFT JOIN os_table_state s ON s.table_id=t.code
                         LEFT JOIN os_reservation_tables r ON r.table_id=t.code AND r.released_at IS NULL
                         WHERE t.active=1 AND t.capacity>=? AND COALESCE(s.state,'free')='free' AND r.reservation_id IS NULL
                         ORDER BY t.capacity,t.sort_order,t.code LIMIT 1''',(guests,)).fetchone()
    if table:
        return {'estimated_minutes':0,'available_table':table['code'],'waiting_ahead':0}
    ahead=int(con.execute("SELECT COUNT(*) c FROM os_waitlist WHERE status IN ('waiting','notified')").fetchone()['c'])
    return {'estimated_minutes':10*(ahead+1),'available_table':None,'waiting_ahead':ahead}


def create_waitlist_entry(con: sqlite3.Connection, name: str, phone: str, guests: int, actor: dict, note: str='') -> dict:
    ensure_phase4_schema(con); _need(actor)
    name=str(name or '').strip(); phone=str(phone or '').strip(); note=str(note or '').strip()
    try: guests=int(guests)
    except Exception: raise ReservationConflict('invalid guest count')
    if len(name)<2 or guests<1 or guests>50 or len(note)>300: raise ReservationConflict('invalid waitlist entry')
    wid='W-'+secrets.token_hex(5).upper()
    con.execute('''INSERT INTO os_waitlist(id,name,phone,guests,note,status,created_by,created_at)
                   VALUES(?,?,?,?,?,'waiting',?,?)''',(wid,name,phone,guests,note,_actor_id(actor),_now()))
    return dict(con.execute('SELECT * FROM os_waitlist WHERE id=?',(wid,)).fetchone())


def seat_reservation(con: sqlite3.Connection, reservation_id: str, actor: dict) -> dict:
    ensure_phase2_schema(con); ensure_phase4_schema(con); _need(actor)
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        booking=_booking(con,reservation_id)
        if booking['status'] in {'cancelled','no_show','seated'}: raise ReservationConflict('reservation not seatable')
        link=con.execute('SELECT * FROM os_reservation_tables WHERE reservation_id=? AND released_at IS NULL',(reservation_id,)).fetchone()
        if not link: raise ReservationConflict('reservation table not assigned')
        try: seating=seat_table(con,link['table_id'],actor,reservation_id)
        except FloorConflict as exc: raise ReservationConflict(str(exc)) from exc
        con.execute("UPDATE bookings SET status='seated' WHERE id=?",(reservation_id,))
        con.execute('UPDATE os_reservation_tables SET seated_order_id=? WHERE reservation_id=?',(seating['order_id'],reservation_id))
        if began: con.commit()
        return {'reservation_id':reservation_id,'table_id':link['table_id'],'order_id':seating['order_id'],'status':'seated'}
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise ReservationConflict('reservation busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def seat_waitlist_entry(con: sqlite3.Connection, waitlist_id: str, table_id: str, actor: dict) -> dict:
    ensure_phase2_schema(con); ensure_phase4_schema(con); _need(actor)
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        row=con.execute('SELECT * FROM os_waitlist WHERE id=?',(waitlist_id,)).fetchone()
        if not row: raise ReservationConflict('waitlist entry not found')
        if row['status'] not in {'waiting','notified'}: raise ReservationConflict('waitlist entry not seatable')
        table=con.execute('SELECT capacity,active FROM tables_map WHERE code=?',(table_id,)).fetchone()
        if not table or not int(table['active']) or int(table['capacity']) < int(row['guests']): raise ReservationConflict('table unavailable')
        try: seating=seat_table(con,table_id,actor,None)
        except FloorConflict as exc: raise ReservationConflict(str(exc)) from exc
        con.execute("UPDATE os_waitlist SET status='seated',seated_at=?,seated_table_id=?,order_id=? WHERE id=?",(_now(),table_id,seating['order_id'],waitlist_id))
        if began: con.commit()
        out=dict(con.execute('SELECT * FROM os_waitlist WHERE id=?',(waitlist_id,)).fetchone())
        return out
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise ReservationConflict('waitlist busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise
