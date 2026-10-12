from __future__ import annotations

import re
import sqlite3
import time

from .migrations import ensure_phase5_schema


class CRMConflict(RuntimeError):
    pass


def _now(): return int(time.time()*1000)
def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')


def normalize_phone(value: str) -> str:
    raw=str(value or '').strip()
    digits=re.sub(r'\D','',raw)
    if len(digits)==9:
        digits='992'+digits
    if len(digits)==12 and digits.startswith('992'):
        return '+'+digits
    if raw.startswith('+') and 10 <= len(digits) <= 15:
        return '+'+digits
    raise CRMConflict('invalid phone')


def get_or_create_customer(con: sqlite3.Connection, phone: str, name: str, actor: dict) -> dict:
    ensure_phase5_schema(con)
    p=normalize_phone(phone); n=str(name or '').strip()
    if len(n)>80: raise CRMConflict('invalid name')
    now=_now()
    con.execute('''INSERT INTO crm_customers(phone,name,created_at,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(phone) DO UPDATE SET name=CASE WHEN excluded.name!='' THEN excluded.name ELSE crm_customers.name END,updated_at=excluded.updated_at''',(p,n,now,now))
    return dict(con.execute('SELECT * FROM crm_customers WHERE phone=?',(p,)).fetchone())


def _completed_orders(con, phone: str):
    p=normalize_phone(phone); out=[]
    for r in con.execute("SELECT id,ts,name,phone,total,status FROM orders WHERE status IN ('done','closed','completed') ORDER BY ts,id"):
        try:
            if normalize_phone(r['phone'])==p: out.append(dict(r))
        except CRMConflict:
            continue
    return out


def recompute_customer_metrics(con: sqlite3.Connection, phone: str) -> dict:
    ensure_phase5_schema(con); p=normalize_phone(phone)
    if not con.execute('SELECT 1 FROM crm_customers WHERE phone=?',(p,)).fetchone():
        get_or_create_customer(con,p,'',{'id':'system','role':'system'})
    orders=_completed_orders(con,p)
    visits=len(orders); lifetime=sum(int(o['total']) for o in orders); last=max([int(o['ts']) for o in orders],default=0)
    con.execute('UPDATE crm_customers SET visits=?,lifetime_spend=?,last_visit_ts=?,updated_at=? WHERE phone=?',(visits,lifetime,last,_now(),p))
    return dict(con.execute('SELECT * FROM crm_customers WHERE phone=?',(p,)).fetchone())


def _favorites(con, phone: str):
    ids=[o['id'] for o in _completed_orders(con,phone)]
    if not ids: return []
    marks=','.join('?' for _ in ids)
    rows=con.execute(f'''SELECT dish_id,MAX(n) name_ru,MAX(n2) name_tj,SUM(q) qty
                         FROM order_items WHERE order_id IN ({marks}) GROUP BY dish_id ORDER BY qty DESC,dish_id LIMIT 10''',ids).fetchall()
    return [dict(r) for r in rows]


def customer_profile(con: sqlite3.Connection, phone: str, *, include_private: bool=False) -> dict:
    p=normalize_phone(phone); row=recompute_customer_metrics(con,p)
    out=dict(row); out['average_spend']=0 if not row['visits'] else round(int(row['lifetime_spend'])/int(row['visits']),2); out['favorite_dishes']=_favorites(con,p)
    if include_private:
        out['tags']=[r['tag'] for r in con.execute('SELECT tag FROM crm_customer_tags WHERE phone=? ORDER BY tag',(p,))]
        out['notes']=[dict(r) for r in con.execute('SELECT note,created_by,created_at FROM crm_customer_notes WHERE phone=? ORDER BY created_at DESC,id DESC',(p,))]
    return out


def add_customer_tag(con: sqlite3.Connection, phone: str, tag: str, actor: dict) -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise CRMConflict('permission denied')
    p=normalize_phone(phone); tag=str(tag or '').strip()
    if not con.execute('SELECT 1 FROM crm_customers WHERE phone=?',(p,)).fetchone(): raise CRMConflict('customer not found')
    if len(tag)<1 or len(tag)>40: raise CRMConflict('invalid tag')
    con.execute('INSERT OR IGNORE INTO crm_customer_tags(phone,tag,created_by,created_at) VALUES(?,?,?,?)',(p,tag,_actor_id(actor),_now()))
    return {'phone':p,'tag':tag}


def add_customer_note(con: sqlite3.Connection, phone: str, note: str, actor: dict) -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise CRMConflict('permission denied')
    p=normalize_phone(phone); note=str(note or '').strip()
    if not con.execute('SELECT 1 FROM crm_customers WHERE phone=?',(p,)).fetchone(): raise CRMConflict('customer not found')
    if len(note)<2 or len(note)>500: raise CRMConflict('invalid note')
    cur=con.execute('INSERT INTO crm_customer_notes(phone,note,created_by,created_at) VALUES(?,?,?,?)',(p,note,_actor_id(actor),_now()))
    return dict(con.execute('SELECT * FROM crm_customer_notes WHERE id=?',(cur.lastrowid,)).fetchone())


def loyalty_balance(con: sqlite3.Connection, phone: str) -> int:
    ensure_phase5_schema(con); p=normalize_phone(phone)
    row=con.execute('SELECT COALESCE(SUM(delta),0) v FROM crm_loyalty_events WHERE phone=?',(p,)).fetchone()
    return int(row['v'])


def _loyalty_event(con: sqlite3.Connection, phone: str, event_type: str, delta: int, actor: dict, idempotency_key: str, reason: str, ref_event_id=None) -> dict:
    p=normalize_phone(phone); key=str(idempotency_key or '').strip(); reason=str(reason or '').strip()
    if not key or len(key)>120: raise CRMConflict('idempotency key required')
    old=con.execute('SELECT * FROM crm_loyalty_events WHERE idempotency_key=?',(key,)).fetchone()
    if old: return dict(old)
    if not con.execute('SELECT 1 FROM crm_customers WHERE phone=?',(p,)).fetchone(): raise CRMConflict('customer not found')
    cur=con.execute('''INSERT INTO crm_loyalty_events(phone,event_type,delta,actor_id,reason,ref_event_id,idempotency_key,created_at)
                       VALUES(?,?,?,?,?,?,?,?)''',(p,event_type,int(delta),_actor_id(actor),reason,ref_event_id,key,_now()))
    return dict(con.execute('SELECT * FROM crm_loyalty_events WHERE id=?',(cur.lastrowid,)).fetchone())


def earn_points(con: sqlite3.Connection, phone: str, points: int, actor: dict, idempotency_key: str, reason: str='') -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager','system'}: raise CRMConflict('permission denied')
    try: points=int(points)
    except Exception: raise CRMConflict('invalid points')
    if points<=0: raise CRMConflict('invalid points')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        out=_loyalty_event(con,phone,'earn',points,actor,idempotency_key,reason)
        if began: con.commit()
        return out
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def redeem_points(con: sqlite3.Connection, phone: str, points: int, actor: dict, idempotency_key: str, reason: str='') -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager','cashier'}: raise CRMConflict('permission denied')
    try: points=int(points)
    except Exception: raise CRMConflict('invalid points')
    if points<=0: raise CRMConflict('invalid points')
    key=str(idempotency_key or '').strip()
    old=con.execute('SELECT * FROM crm_loyalty_events WHERE idempotency_key=?',(key,)).fetchone()
    if old: return dict(old)
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        if loyalty_balance(con,phone) < points: raise CRMConflict('insufficient points')
        out=_loyalty_event(con,phone,'redeem',-points,actor,key,reason)
        if began: con.commit()
        return out
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def reverse_loyalty_event(con: sqlite3.Connection, event_id: int, actor: dict, reason: str) -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise CRMConflict('permission denied')
    reason=str(reason or '').strip()
    if len(reason)<2: raise CRMConflict('reason required')
    target=con.execute("SELECT * FROM crm_loyalty_events WHERE id=? AND event_type IN ('earn','redeem')",(int(event_id),)).fetchone()
    if not target: raise CRMConflict('loyalty event not found')
    key=f"reverse:{target['id']}"
    old=con.execute('SELECT * FROM crm_loyalty_events WHERE idempotency_key=?',(key,)).fetchone()
    if old: return dict(old)
    if loyalty_balance(con,target['phone']) - int(target['delta']) < 0:
        raise CRMConflict('reversal would make balance negative')
    return _loyalty_event(con,target['phone'],'reversal',-int(target['delta']),actor,key,reason,target['id'])
