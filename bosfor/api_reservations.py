from __future__ import annotations

from .reservations import (
    assign_reservation_table, cancel_reservation, create_waitlist_entry, mark_no_show,
    quote_wait, seat_reservation, seat_waitlist_entry,
)

READ_ROLES={'owner','manager','waiter'}

def _need(actor, roles=READ_ROLES):
    if actor.get('role') not in roles: raise PermissionError('permission denied')

def list_reservations(con, actor):
    _need(actor)
    rows=con.execute('''SELECT b.id,b.ts,b.name,b.phone,b.guests,b.date,b.time,b.note,b.status,
                               rt.table_id,rt.assigned_at,rt.seated_order_id,rt.released_at
                        FROM bookings b LEFT JOIN os_reservation_tables rt ON rt.reservation_id=b.id
                        ORDER BY b.ts DESC LIMIT 1000''').fetchall()
    return [dict(r) for r in rows]

def list_waitlist(con, actor):
    _need(actor)
    return [dict(r) for r in con.execute("SELECT * FROM os_waitlist ORDER BY CASE status WHEN 'waiting' THEN 0 WHEN 'notified' THEN 1 ELSE 2 END,created_at,id LIMIT 1000")]

def wait_quote(con, guests, actor):
    _need(actor)
    return quote_wait(con, guests)

def handle_reservation_action(con, action: str, payload: dict, actor: dict):
    _need(actor)
    if action=='waitlist':
        return 201,create_waitlist_entry(con,payload.get('name',''),payload.get('phone',''),payload.get('guests'),actor,note=payload.get('note',''))
    if action=='assign':
        return 200,assign_reservation_table(con,str(payload.get('reservation_id','')),str(payload.get('table_id','')),actor)
    if action=='seat':
        if payload.get('reservation_id'):
            return 201,seat_reservation(con,str(payload.get('reservation_id')),actor)
        return 201,seat_waitlist_entry(con,str(payload.get('waitlist_id','')),str(payload.get('table_id','')),actor)
    if action=='cancel':
        return 200,cancel_reservation(con,str(payload.get('reservation_id','')),actor,str(payload.get('reason','')))
    if action=='no-show':
        return 200,mark_no_show(con,str(payload.get('reservation_id','')),actor,str(payload.get('reason','')))
    raise KeyError(action)
