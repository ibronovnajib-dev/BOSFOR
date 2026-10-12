from __future__ import annotations

import sqlite3
import time
from collections import defaultdict

from .migrations import ensure_phase2_schema
from .orders import OrderConflict, transition_order


class KitchenConflict(RuntimeError):
    pass


def _now(): return int(time.time()*1000)
def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')


def set_dish_station(con: sqlite3.Connection, dish_id: str, station_id: str) -> None:
    ensure_phase2_schema(con)
    station=con.execute('SELECT id FROM os_kitchen_stations WHERE id=? AND active=1',(station_id,)).fetchone()
    dish=con.execute('SELECT id FROM dishes WHERE id=?',(dish_id,)).fetchone()
    if not station or not dish: raise KitchenConflict('dish or station not found')
    con.execute('INSERT OR REPLACE INTO os_dish_station(dish_id,station_id) VALUES(?,?)',(dish_id,station_id))


def set_dish_availability(con, dish_id: str, available: bool, actor: dict, reason: str) -> None:
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager','kitchen'}: raise KitchenConflict('permission denied')
    if not con.execute('SELECT 1 FROM dishes WHERE id=?',(dish_id,)).fetchone(): raise KitchenConflict('dish not found')
    con.execute('''INSERT INTO os_dish_availability(dish_id,available,reason,updated_at,actor_id) VALUES(?,?,?,?,?)
                   ON CONFLICT(dish_id) DO UPDATE SET available=excluded.available,reason=excluded.reason,updated_at=excluded.updated_at,actor_id=excluded.actor_id''',
                (dish_id,1 if available else 0,str(reason or '')[:200],_now(),_actor_id(actor)))


def _ticket_dict(con, ticket_id: int) -> dict:
    r=con.execute('SELECT * FROM os_kitchen_tickets WHERE id=?',(ticket_id,)).fetchone()
    if not r: raise KitchenConflict('ticket not found')
    out=dict(r)
    items=con.execute('''SELECT kti.order_item_id,kti.qty,oi.dish_id,oi.name_ru,oi.name_tj,oi.modifiers_json,oi.note
                         FROM os_kitchen_ticket_items kti JOIN os_order_items oi ON oi.id=kti.order_item_id
                         WHERE kti.ticket_id=? ORDER BY kti.order_item_id''',(ticket_id,)).fetchall()
    out['items']=[dict(x) for x in items]
    now=_now(); elapsed=max(0,(now-int(out['sent_at']))//60000)
    out['elapsed_minutes']=int(elapsed)
    out['overdue']=out['state'] in {'queued','preparing'} and elapsed>=int(out['target_minutes'])
    return out


def route_unsent_items(con: sqlite3.Connection, order_id: str, actor: dict) -> list[dict]:
    ensure_phase2_schema(con)
    began=False
    try:
        if not con.in_transaction:
            con.execute('BEGIN IMMEDIATE'); began=True
        order=con.execute('SELECT * FROM os_orders WHERE id=?',(order_id,)).fetchone()
        if not order or order['state'] in {'closed','cancelled'}:
            raise KitchenConflict('order not routable')
        rows=con.execute('''SELECT oi.*, COALESCE(ds.station_id,'default') station_id,
                           COALESCE(ks.target_minutes,15) target_minutes
                           FROM os_order_items oi
                           LEFT JOIN os_dish_station ds ON ds.dish_id=oi.dish_id
                           LEFT JOIN os_kitchen_stations ks ON ks.id=COALESCE(ds.station_id,'default')
                           WHERE oi.order_id=? AND oi.status='active' AND oi.qty>oi.sent_qty ORDER BY oi.id''',(order_id,)).fetchall()
        if not rows:
            if began: con.commit()
            return []
        groups=defaultdict(list)
        for r in rows: groups[r['station_id']].append(r)
        tickets=[]
        for station_id, items in groups.items():
            station=con.execute('SELECT target_minutes,active FROM os_kitchen_stations WHERE id=?',(station_id,)).fetchone()
            if not station or not int(station['active']): raise KitchenConflict('station unavailable')
            cur=con.execute('''INSERT INTO os_kitchen_tickets(order_id,station_id,state,priority,sent_at,target_minutes,actor_id)
                               VALUES(?,?, 'queued',0,?,?,?)''',(order_id,station_id,_now(),int(station['target_minutes']),_actor_id(actor)))
            tid=cur.lastrowid
            for item in items:
                qty=int(item['qty'])-int(item['sent_qty'])
                if qty<=0: continue
                con.execute('INSERT INTO os_kitchen_ticket_items(ticket_id,order_item_id,qty) VALUES(?,?,?)',(tid,item['id'],qty))
                con.execute('UPDATE os_order_items SET sent_qty=sent_qty+? WHERE id=?',(qty,item['id']))
            tickets.append(_ticket_dict(con,tid))
        if order['state']=='open': transition_order(con,order_id,'confirmed',actor)
        if began: con.commit()
        return tickets
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise KitchenConflict('kitchen send busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


TICKET_GRAPH={
    'queued': {'preparing','ready','cancelled'},
    'preparing': {'ready','cancelled'},
    'ready': {'recalled'},
    'recalled': set(),
    'cancelled': set(),
}


def set_ticket_state(con: sqlite3.Connection, ticket_id: int, target: str, actor: dict) -> dict:
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager','kitchen'}: raise KitchenConflict('permission denied')
    ticket=con.execute('SELECT * FROM os_kitchen_tickets WHERE id=?',(ticket_id,)).fetchone()
    if not ticket: raise KitchenConflict('ticket not found')
    if target==ticket['state']: return _ticket_dict(con,ticket_id)
    if target not in TICKET_GRAPH.get(ticket['state'],set()): raise KitchenConflict('invalid ticket transition')
    now=_now(); started=ticket['started_at']; ready=ticket['ready_at']
    if target=='preparing' and not started: started=now
    if target=='ready':
        if not started: started=now
        ready=now
    con.execute('UPDATE os_kitchen_tickets SET state=?,started_at=?,ready_at=? WHERE id=?',(target,started,ready,ticket_id))
    oid=ticket['order_id']
    order=con.execute('SELECT state FROM os_orders WHERE id=?',(oid,)).fetchone()
    if order:
        try:
            if target=='preparing' and order['state']=='confirmed': transition_order(con,oid,'preparing',actor)
            if target=='ready':
                state=con.execute('SELECT state FROM os_orders WHERE id=?',(oid,)).fetchone()['state']
                if state=='confirmed':
                    transition_order(con,oid,'preparing',actor); state='preparing'
                active=con.execute("SELECT COUNT(*) c FROM os_kitchen_tickets WHERE order_id=? AND state NOT IN ('ready','recalled','cancelled')",(oid,)).fetchone()['c']
                if not active and state=='preparing': transition_order(con,oid,'ready',actor)
        except OrderConflict as exc:
            raise KitchenConflict(str(exc)) from exc
    return _ticket_dict(con,ticket_id)


def list_tickets(con: sqlite3.Connection, actor: dict, active_only: bool = True) -> list[dict]:
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager','kitchen','waiter','cashier'}: raise KitchenConflict('permission denied')
    where="WHERE state IN ('queued','preparing','ready')" if active_only else ''
    rows=con.execute(f'SELECT id FROM os_kitchen_tickets {where} ORDER BY priority DESC,sent_at,id').fetchall()
    return [_ticket_dict(con,int(r['id'])) for r in rows]
