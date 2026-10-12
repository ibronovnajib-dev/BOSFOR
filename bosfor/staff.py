from __future__ import annotations

import sqlite3
import time

from .migrations import ensure_phase4_schema


class StaffConflict(RuntimeError):
    pass


def _now() -> int:
    return int(time.time()*1000)


def _actor_id(actor: dict) -> str:
    return str(actor.get('id') or actor.get('username') or 'system')


def _effective_events(con: sqlite3.Connection, staff_id: str):
    base=[dict(r) for r in con.execute("SELECT * FROM os_clock_events WHERE staff_id=? AND event_type IN ('in','out') ORDER BY id",(staff_id,))]
    corrections={}
    for r in con.execute("SELECT * FROM os_clock_events WHERE staff_id=? AND event_type='correction' ORDER BY id",(staff_id,)):
        corrections[int(r['ref_event_id'])]=int(r['occurred_at'])
    events=[]
    for r in base:
        events.append({'id':r['id'],'event_type':r['event_type'],'occurred_at':corrections.get(int(r['id']),int(r['occurred_at']))})
    events.sort(key=lambda x:(x['occurred_at'],x['id']))
    return events


def _open_clock_in(con: sqlite3.Connection, staff_id: str):
    open_ev=None
    for ev in _effective_events(con,staff_id):
        if ev['event_type']=='in':
            if open_ev is not None:
                raise StaffConflict('clock event sequence invalid')
            open_ev=ev
        else:
            if open_ev is None:
                raise StaffConflict('clock event sequence invalid')
            open_ev=None
    return open_ev


def schedule_shift(con: sqlite3.Connection, staff_id: str, start_at: int, end_at: int, actor: dict, note: str='') -> dict:
    ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise StaffConflict('permission denied')
    staff_id=str(staff_id or '').strip(); note=str(note or '').strip()
    try: start_at=int(start_at); end_at=int(end_at)
    except Exception: raise StaffConflict('invalid shift time')
    if not staff_id or start_at < 0 or end_at <= start_at or len(note)>300: raise StaffConflict('invalid shift')
    cur=con.execute('INSERT INTO os_staff_shifts(staff_id,start_at,end_at,note,created_by,created_at) VALUES(?,?,?,?,?,?)',(staff_id,start_at,end_at,note,_actor_id(actor),_now()))
    return dict(con.execute('SELECT * FROM os_staff_shifts WHERE id=?',(cur.lastrowid,)).fetchone())


def clock_in(con: sqlite3.Connection, staff_id: str, actor: dict, *, at: int | None=None) -> dict:
    ensure_phase4_schema(con); staff_id=str(staff_id or '').strip()
    if not staff_id: raise StaffConflict('staff_id required')
    if actor.get('role') not in {'owner','manager','waiter','cashier','kitchen'}: raise StaffConflict('permission denied')
    if actor.get('role') not in {'owner','manager'} and _actor_id(actor) != staff_id:
        raise StaffConflict('permission denied')
    if _open_clock_in(con,staff_id) is not None: raise StaffConflict('already clocked in')
    at=_now() if at is None else int(at)
    cur=con.execute("INSERT INTO os_clock_events(staff_id,event_type,occurred_at,actor_id,created_at) VALUES(?,'in',?,?,?)",(staff_id,at,_actor_id(actor),_now()))
    return dict(con.execute('SELECT * FROM os_clock_events WHERE id=?',(cur.lastrowid,)).fetchone())


def clock_out(con: sqlite3.Connection, staff_id: str, actor: dict, *, at: int | None=None) -> dict:
    ensure_phase4_schema(con); staff_id=str(staff_id or '').strip()
    if actor.get('role') not in {'owner','manager','waiter','cashier','kitchen'}: raise StaffConflict('permission denied')
    if actor.get('role') not in {'owner','manager'} and _actor_id(actor) != staff_id: raise StaffConflict('permission denied')
    open_ev=_open_clock_in(con,staff_id)
    if open_ev is None: raise StaffConflict('not clocked in')
    at=_now() if at is None else int(at)
    if at <= int(open_ev['occurred_at']): raise StaffConflict('clock-out must be after clock-in')
    cur=con.execute("INSERT INTO os_clock_events(staff_id,event_type,occurred_at,actor_id,created_at) VALUES(?,'out',?,?,?)",(staff_id,at,_actor_id(actor),_now()))
    return dict(con.execute('SELECT * FROM os_clock_events WHERE id=?',(cur.lastrowid,)).fetchone())


def correct_clock_event(con: sqlite3.Connection, event_id: int, corrected_at: int, actor: dict, reason: str) -> dict:
    ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise StaffConflict('permission denied')
    reason=str(reason or '').strip()
    if len(reason)<2: raise StaffConflict('reason required')
    target=con.execute("SELECT * FROM os_clock_events WHERE id=? AND event_type IN ('in','out')",(int(event_id),)).fetchone()
    if not target: raise StaffConflict('clock event not found')
    corrected_at=int(corrected_at)
    cur=con.execute("INSERT INTO os_clock_events(staff_id,event_type,occurred_at,actor_id,reason,ref_event_id,created_at) VALUES(?,'correction',?,?,?,?,?)",(target['staff_id'],corrected_at,_actor_id(actor),reason,target['id'],_now()))
    # Validate the effective sequence while still preserving append-only history.
    _effective_events(con,target['staff_id'])
    return dict(con.execute('SELECT * FROM os_clock_events WHERE id=?',(cur.lastrowid,)).fetchone())


def hours_summary(con: sqlite3.Connection, staff_id: str, start_at: int, end_at: int) -> dict:
    ensure_phase4_schema(con); start_at=int(start_at); end_at=int(end_at)
    if end_at <= start_at: raise StaffConflict('invalid range')
    total_ms=0; open_ev=None
    for ev in _effective_events(con,str(staff_id)):
        if ev['event_type']=='in':
            if open_ev is None: open_ev=ev
        else:
            if open_ev is None: continue
            a=max(start_at,int(open_ev['occurred_at'])); b=min(end_at,int(ev['occurred_at']))
            if b>a: total_ms += b-a
            open_ev=None
    return {'staff_id':str(staff_id),'worked_minutes':total_ms//60000,'open_clock_in':None if open_ev is None else int(open_ev['occurred_at'])}
