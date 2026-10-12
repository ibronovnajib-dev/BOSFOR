from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any

from .migrations import ensure_phase2_schema


class OrderConflict(RuntimeError):
    pass


VALID_TYPES = {'delivery','pickup','dinein','pos_dinein'}
STATE_GRAPH = {
    'open': {'confirmed','cancelled'},
    'confirmed': {'preparing','cancelled'},
    'preparing': {'ready','cancelled'},
    'ready': {'served','out_for_delivery','cancelled'},
    'served': {'paid'},
    'out_for_delivery': {'paid'},
    'paid': {'closed'},
    'closed': set(),
    'cancelled': set(),
}


def _now() -> int:
    return int(time.time() * 1000)


def _actor_id(actor: dict[str, Any]) -> str:
    return str(actor.get('id') or actor.get('username') or 'system')


def _rowdict(row: sqlite3.Row | None):
    return dict(row) if row is not None else None


def _order(con: sqlite3.Connection, order_id: str) -> dict:
    row = con.execute('SELECT * FROM os_orders WHERE id=?', (order_id,)).fetchone()
    if not row:
        raise OrderConflict('order not found')
    return dict(row)


def create_pos_order(con: sqlite3.Connection, actor: dict, order_type: str, table_id: str | None = None) -> dict:
    ensure_phase2_schema(con)
    if order_type not in VALID_TYPES:
        raise OrderConflict('invalid order type')
    if order_type in {'dinein','pos_dinein'}:
        if not table_id:
            raise OrderConflict('table required')
        table = con.execute('SELECT code,active FROM tables_map WHERE code=?', (table_id,)).fetchone()
        if not table or not int(table['active']):
            raise OrderConflict('table unavailable')
    oid = 'POS-' + secrets.token_hex(6).upper()
    con.execute(
        'INSERT INTO os_orders(id,created_at,created_by,order_type,table_id,state) VALUES(?,?,?,?,?,\'open\')',
        (oid, _now(), _actor_id(actor), order_type, table_id),
    )
    return _order(con, oid)


def _assert_mutable(order: dict) -> None:
    if order['state'] in {'closed','cancelled'}:
        raise OrderConflict('order is locked')


def add_item(con: sqlite3.Connection, order_id: str, dish_id: str, qty: int, modifiers, note: str) -> dict:
    ensure_phase2_schema(con)
    order = _order(con, order_id)
    _assert_mutable(order)
    if not isinstance(qty, int) or qty < 1 or qty > 50:
        raise OrderConflict('invalid quantity')
    dish = con.execute('SELECT id,price,ru,tj,off FROM dishes WHERE id=?', (dish_id,)).fetchone()
    if not dish or int(dish['off']):
        raise OrderConflict('dish unavailable')
    availability = con.execute('SELECT available FROM os_dish_availability WHERE dish_id=?', (dish_id,)).fetchone()
    if availability is not None and not int(availability['available']):
        raise OrderConflict('dish unavailable')
    if not isinstance(modifiers, (dict, list)):
        raise OrderConflict('invalid modifiers')
    note = str(note or '').strip()
    if len(note) > 300:
        raise OrderConflict('note too long')
    cur = con.execute(
        '''INSERT INTO os_order_items(order_id,dish_id,qty,unit_price,name_ru,name_tj,modifiers_json,note,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)''',
        (order_id, dish_id, qty, int(dish['price']), dish['ru'], dish['tj'], json.dumps(modifiers, ensure_ascii=False, separators=(',',':')), note, _now()),
    )
    recalculate_order(con, order_id)
    row = con.execute('SELECT * FROM os_order_items WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def recalculate_order(con: sqlite3.Connection, order_id: str) -> dict:
    _order(con, order_id)
    subtotal = int(con.execute(
        "SELECT COALESCE(SUM(qty*unit_price),0) AS v FROM os_order_items WHERE order_id=? AND status='active'",
        (order_id,),
    ).fetchone()['v'])
    discount = int(con.execute(
        'SELECT COALESCE(SUM(amount),0) AS v FROM os_order_adjustments WHERE order_id=?',
        (order_id,),
    ).fetchone()['v'])
    discount = min(subtotal, max(0, discount))
    delivery_fee=0
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='os_delivery_orders'").fetchone():
        row=con.execute('SELECT fee FROM os_delivery_orders WHERE order_id=?',(order_id,)).fetchone()
        if row: delivery_fee=int(row['fee'])
    total = subtotal - discount + delivery_fee
    con.execute('UPDATE os_orders SET subtotal=?,discount_total=?,total=?,version=version+1 WHERE id=?', (subtotal, discount, total, order_id))
    return {'subtotal': subtotal, 'discount': discount, 'total': total}


def transition_order(con: sqlite3.Connection, order_id: str, target: str, actor: dict, reason: str | None = None) -> dict:
    ensure_phase2_schema(con)
    inventory_target = target in {'served','out_for_delivery','cancelled'}
    if inventory_target:
        from .migrations import ensure_phase3_schema
        ensure_phase3_schema(con)
    began = inventory_target and not con.in_transaction
    try:
        if began:
            con.execute('BEGIN IMMEDIATE')
        order = _order(con, order_id)
        current = order['state']
        if current == target:
            if began:
                con.commit()
            return order
        if current == 'closed' and target == 'open':
            if actor.get('role') not in {'owner','manager'} or not str(reason or '').strip():
                raise OrderConflict('manager reason required to reopen')
            con.execute('UPDATE os_orders SET state=\'open\',closed_at=NULL,reopened_reason=?,version=version+1 WHERE id=?', (str(reason).strip(), order_id))
            result = _order(con, order_id)
            if began:
                con.commit()
            return result
        if target not in STATE_GRAPH.get(current, set()):
            raise OrderConflict(f'invalid transition {current}->{target}')
        if target in {'paid','closed'}:
            from .finance_ledger import payment_balance
            if payment_balance(con, order_id)['due'] != 0:
                raise OrderConflict('order has unpaid balance')
        closed_at = _now() if target == 'closed' else None
        con.execute('UPDATE os_orders SET state=?,closed_at=?,version=version+1 WHERE id=?', (target, closed_at, order_id))
        if target in {'served','out_for_delivery'}:
            from .inventory import consume_order_items
            consume_order_items(con, order_id, target, actor)
        elif target == 'cancelled':
            from .inventory import reverse_order_consumption
            reverse_order_consumption(con, order_id, actor, str(reason or 'order cancelled'))
        if target == 'closed' and order.get('table_id'):
            con.execute("UPDATE os_table_state SET state='cleaning',active_order_id=NULL,seating_id=NULL,version=version+1,updated_at=? WHERE table_id=? AND active_order_id=?", (_now(), order['table_id'], order_id))
            con.execute('UPDATE os_seatings SET ended_at=? WHERE table_id=? AND order_id=? AND ended_at IS NULL', (_now(), order['table_id'], order_id))
        result = _order(con, order_id)
        if began:
            con.commit()
        return result
    except Exception:
        if began and con.in_transaction:
            con.rollback()
        raise
