from __future__ import annotations

from .tables import FloorConflict, merge_orders, move_order, seat_table, set_table_state

FLOOR_ROLES={'owner','manager','waiter'}


def _need(actor):
    if actor.get('role') not in FLOOR_ROLES:
        raise PermissionError('permission denied')


def list_floor(con, actor):
    _need(actor)
    tables=con.execute('SELECT code,label,capacity,zone,active,sort_order FROM tables_map ORDER BY sort_order,code').fetchall()
    out=[]
    for t in tables:
        item=dict(t)
        state=con.execute('SELECT state,version,active_order_id,seating_id,updated_at FROM os_table_state WHERE table_id=?',(t['code'],)).fetchone()
        item.update(dict(state) if state else {'state':'free','version':1,'active_order_id':None,'seating_id':None,'updated_at':0})
        out.append(item)
    return out


def handle_floor_action(con, action, payload, actor):
    _need(actor)
    if action=='seat': return 201, seat_table(con,str(payload.get('table_id','')),actor,payload.get('reservation_id'))
    if action=='state': return 200, set_table_state(con,str(payload.get('table_id','')),str(payload.get('target','')),actor)
    if action=='move': return 200, move_order(con,str(payload.get('order_id','')),str(payload.get('to_table_id','')),actor)
    if action=='merge': return 200, merge_orders(con,str(payload.get('source_id','')),str(payload.get('target_id','')),actor)
    raise KeyError(action)
