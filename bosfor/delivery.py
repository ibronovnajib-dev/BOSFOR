from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re
import secrets
import sqlite3
import time

from .migrations import ensure_phase2_schema, ensure_phase5_schema

class DeliveryConflict(RuntimeError): pass

def _now(): return int(time.time()*1000)
def _actor_id(a): return str(a.get('id') or a.get('username') or 'system')
TIME_RE=re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d$')

def create_zone(con: sqlite3.Connection, zone_id: str, name: str, fee: int, min_order: int, service_start: str, service_end: str, actor: dict) -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise DeliveryConflict('permission denied')
    zone_id=str(zone_id or '').strip(); name=str(name or '').strip(); service_start=str(service_start); service_end=str(service_end)
    try: fee=int(fee); min_order=int(min_order)
    except Exception: raise DeliveryConflict('invalid zone values')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',zone_id) or len(name)<2 or fee<0 or min_order<0 or not TIME_RE.fullmatch(service_start) or not TIME_RE.fullmatch(service_end): raise DeliveryConflict('invalid zone')
    con.execute('''INSERT INTO delivery_zones(id,name,fee,min_order,service_start,service_end,active,updated_at,updated_by) VALUES(?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,fee=excluded.fee,min_order=excluded.min_order,service_start=excluded.service_start,service_end=excluded.service_end,active=1,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',(zone_id,name,fee,min_order,service_start,service_end,_now(),_actor_id(actor)))
    return dict(con.execute('SELECT * FROM delivery_zones WHERE id=?',(zone_id,)).fetchone())

def _minutes(v: str):
    h,m=map(int,v.split(':')); return h*60+m

def _when_minutes(when) -> int:
    if isinstance(when, datetime): dt=when
    else: dt=datetime.fromtimestamp(int(when)/1000,timezone(timedelta(hours=5)))
    return dt.hour*60+dt.minute

def quote_delivery(con: sqlite3.Connection, zone_id: str, subtotal: int, when) -> dict:
    ensure_phase5_schema(con)
    z=con.execute('SELECT * FROM delivery_zones WHERE id=? AND active=1',(str(zone_id),)).fetchone()
    if not z: raise DeliveryConflict('delivery zone not found')
    try: subtotal=int(subtotal)
    except Exception: raise DeliveryConflict('invalid subtotal')
    if subtotal < int(z['min_order']): raise DeliveryConflict('minimum order not reached')
    nowm=_when_minutes(when); a=_minutes(z['service_start']); b=_minutes(z['service_end'])
    open_now=(a<=nowm<=b) if a<=b else (nowm>=a or nowm<=b)
    if not open_now: raise DeliveryConflict('delivery unavailable at this time')
    return {'zone_id':z['id'],'zone_name':z['name'],'fee':int(z['fee']),'min_order':int(z['min_order']),'service_start':z['service_start'],'service_end':z['service_end']}

def attach_delivery_quote(con: sqlite3.Connection, order_id: str, zone_id: str, subtotal: int, when, actor: dict) -> dict:
    ensure_phase2_schema(con); ensure_phase5_schema(con)
    o=con.execute('SELECT * FROM os_orders WHERE id=?',(order_id,)).fetchone()
    if not o or o['order_type']!='delivery': raise DeliveryConflict('delivery order not found')
    q=quote_delivery(con,zone_id,subtotal,when)
    tracking_token=secrets.token_urlsafe(24)
    con.execute('''INSERT INTO os_delivery_orders(order_id,zone_id,zone_name,fee,min_order,service_start,service_end,quoted_at,state,tracking_token)
                   VALUES(?,?,?,?,?,?,?,?,'quoted',?)
                   ON CONFLICT(order_id) DO NOTHING''',(order_id,q['zone_id'],q['zone_name'],q['fee'],q['min_order'],q['service_start'],q['service_end'],_now(),tracking_token))
    con.execute("UPDATE os_delivery_orders SET tracking_token=? WHERE order_id=? AND (tracking_token IS NULL OR tracking_token='')",(tracking_token,order_id))
    from .orders import recalculate_order
    recalculate_order(con,order_id)
    return dict(con.execute('SELECT * FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone())

def assign_courier(con: sqlite3.Connection, order_id: str, courier_id: str, actor: dict) -> dict:
    ensure_phase5_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise DeliveryConflict('permission denied')
    courier_id=str(courier_id or '').strip()
    if not courier_id: raise DeliveryConflict('courier required')
    row=con.execute('SELECT * FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone()
    if not row or row['state'] in {'delivered','cancelled'}: raise DeliveryConflict('delivery not assignable')
    con.execute("UPDATE os_delivery_orders SET courier_id=?,state='assigned',assigned_at=? WHERE order_id=?",(courier_id,_now(),order_id))
    return dict(con.execute('SELECT * FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone())

STATE={'assigned':{'picked_up','cancelled'},'picked_up':{'delivered','cancelled'},'quoted':{'cancelled'},'delivered':set(),'cancelled':set()}
def transition_delivery(con: sqlite3.Connection, order_id: str, target: str, actor: dict) -> dict:
    ensure_phase5_schema(con); row=con.execute('SELECT * FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone()
    if not row: raise DeliveryConflict('delivery not found')
    if actor.get('role')=='courier':
        if row['courier_id']!=_actor_id(actor): raise DeliveryConflict('permission denied')
    elif actor.get('role') not in {'owner','manager'}: raise DeliveryConflict('permission denied')
    if target not in STATE.get(row['state'],set()): raise DeliveryConflict(f"invalid delivery transition {row['state']}->{target}")
    fields={'picked_up':'picked_up_at','delivered':'delivered_at'}; tsfield=fields.get(target)
    if tsfield: con.execute(f'UPDATE os_delivery_orders SET state=?,{tsfield}=? WHERE order_id=?',(target,_now(),order_id))
    else: con.execute('UPDATE os_delivery_orders SET state=? WHERE order_id=?',(target,order_id))
    return dict(con.execute('SELECT * FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone())

def safe_tracking_view(con: sqlite3.Connection, order_id: str) -> dict:
    ensure_phase5_schema(con); r=con.execute('SELECT order_id,zone_name,fee,state,assigned_at,picked_up_at,delivered_at FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone()
    if not r: raise DeliveryConflict('delivery not found')
    return dict(r)

def safe_tracking_by_token(con: sqlite3.Connection, token: str) -> dict:
    ensure_phase5_schema(con)
    token=str(token or '').strip()
    if len(token)<24 or len(token)>100: raise DeliveryConflict('delivery not found')
    r=con.execute('SELECT order_id,zone_name,fee,state,assigned_at,picked_up_at,delivered_at FROM os_delivery_orders WHERE tracking_token=?',(token,)).fetchone()
    if not r: raise DeliveryConflict('delivery not found')
    return dict(r)
