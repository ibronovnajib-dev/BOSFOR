from __future__ import annotations

from .finance_ledger import LedgerConflict, apply_discount, payment_balance, record_payment, refund_payment
from .orders import OrderConflict, add_item, create_pos_order, transition_order
from .kitchen import route_unsent_items
from .tables import seat_table


POS_READ_ROLES={'owner','manager','cashier','waiter'}
POS_WRITE_ROLES={'owner','manager','cashier','waiter'}
PAYMENT_ROLES={'owner','manager','cashier'}
DISCOUNT_ROLES={'owner','manager'}


def _need(actor, roles):
    if actor.get('role') not in roles:
        raise PermissionError('permission denied')


def list_orders(con, actor):
    _need(actor, POS_READ_ROLES)
    rows=con.execute("SELECT * FROM os_orders WHERE state NOT IN ('closed','cancelled') ORDER BY created_at DESC LIMIT 500").fetchall()
    out=[]
    for r in rows:
        o=dict(r)
        items=con.execute("SELECT * FROM os_order_items WHERE order_id=? ORDER BY id",(o['id'],)).fetchall()
        o['items']=[dict(x) for x in items]
        o['payment']=payment_balance(con,o['id'])
        out.append(o)
    return out


def handle_pos_action(con, action, payload, actor, idempotency_key=''):
    if action=='orders':
        _need(actor, POS_WRITE_ROLES)
        order_type=str(payload.get('order_type',''))
        table_id=payload.get('table_id')
        if order_type in {'dinein','pos_dinein'}:
            seating=seat_table(con,str(table_id or ''),actor)
            row=con.execute('SELECT * FROM os_orders WHERE id=?',(seating['order_id'],)).fetchone()
            return 201, dict(row)
        return 201, create_pos_order(con,actor,order_type,table_id)
    if action=='items':
        _need(actor, POS_WRITE_ROLES)
        return 201, add_item(con,str(payload.get('order_id','')),str(payload.get('dish_id','')),int(payload.get('qty',0)),payload.get('modifiers',{}),str(payload.get('note','')))
    if action=='send':
        _need(actor, POS_WRITE_ROLES)
        return 201, route_unsent_items(con, str(payload.get('order_id','')), actor)
    if action=='payments':
        _need(actor, PAYMENT_ROLES)
        return 201, record_payment(con,str(payload.get('order_id','')),actor,str(payload.get('method','')),payload.get('amount',0),idempotency_key)
    if action=='discounts':
        _need(actor, DISCOUNT_ROLES)
        return 201, apply_discount(con,str(payload.get('order_id','')),actor,str(payload.get('kind','')),payload.get('value',0),str(payload.get('reason','')))
    if action=='refunds':
        _need(actor, PAYMENT_ROLES)
        return 201, refund_payment(con,int(payload.get('payment_id',0)),actor,payload.get('amount',0),str(payload.get('reason','')))
    if action=='transition':
        _need(actor, POS_WRITE_ROLES)
        return 200, transition_order(con,str(payload.get('order_id','')),str(payload.get('target','')),actor,payload.get('reason'))
    if action=='close':
        _need(actor, PAYMENT_ROLES)
        oid=str(payload.get('order_id',''))
        row=con.execute('SELECT state FROM os_orders WHERE id=?',(oid,)).fetchone()
        if not row: raise OrderConflict('order not found')
        if row['state'] in {'served','out_for_delivery'}:
            transition_order(con,oid,'paid',actor)
        return 200, transition_order(con,oid,'closed',actor)
    raise KeyError(action)
