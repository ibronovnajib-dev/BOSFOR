from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .delivery import assign_courier, attach_delivery_quote, create_zone, transition_delivery

MANAGER_ROLES={'owner','manager'}

def _actor_id(actor): return str(actor.get('id') or actor.get('username') or '')

def _need_manager(actor):
    if actor.get('role') not in MANAGER_ROLES: raise PermissionError('permission denied')

def list_zones(con, actor):
    if actor.get('role') not in MANAGER_ROLES|{'courier'}: raise PermissionError('permission denied')
    return [dict(r) for r in con.execute('SELECT * FROM delivery_zones ORDER BY name,id')]

def list_deliveries(con, actor):
    role=actor.get('role')
    if role in MANAGER_ROLES:
        rows=con.execute('SELECT order_id,zone_id,zone_name,fee,min_order,service_start,service_end,quoted_at,state,courier_id,assigned_at,picked_up_at,delivered_at FROM os_delivery_orders ORDER BY quoted_at DESC LIMIT 1000').fetchall()
    elif role=='courier':
        rows=con.execute('SELECT order_id,zone_id,zone_name,fee,min_order,service_start,service_end,quoted_at,state,courier_id,assigned_at,picked_up_at,delivered_at FROM os_delivery_orders WHERE courier_id=? ORDER BY quoted_at DESC LIMIT 500',(_actor_id(actor),)).fetchall()
    else: raise PermissionError('permission denied')
    return [dict(r) for r in rows]

def handle_delivery_action(con, action, payload, actor):
    if action=='zone':
        _need_manager(actor)
        return 201,create_zone(con,payload.get('id'),payload.get('name'),payload.get('fee'),payload.get('min_order'),payload.get('service_start'),payload.get('service_end'),actor)
    if action=='attach':
        _need_manager(actor)
        now=datetime.now(timezone(timedelta(hours=5)))
        return 201,attach_delivery_quote(con,str(payload.get('order_id','')),str(payload.get('zone_id','')),payload.get('subtotal'),now,actor)
    if action=='assign':
        _need_manager(actor)
        return 200,assign_courier(con,str(payload.get('order_id','')),str(payload.get('courier_id','')),actor)
    if action=='state':
        if actor.get('role')=='courier':
            row=con.execute('SELECT courier_id FROM os_delivery_orders WHERE order_id=?',(str(payload.get('order_id','')),)).fetchone()
            if not row: raise KeyError('delivery not found')
            if row['courier_id']!=_actor_id(actor): raise PermissionError('permission denied')
        elif actor.get('role') not in MANAGER_ROLES:
            raise PermissionError('permission denied')
        return 200,transition_delivery(con,str(payload.get('order_id','')),str(payload.get('state','')),actor)
    raise KeyError(action)
