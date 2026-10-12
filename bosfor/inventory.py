from __future__ import annotations

import re
import secrets
import sqlite3
import time
from decimal import Decimal, InvalidOperation, getcontext

from .migrations import ensure_phase3_schema

getcontext().prec = 28


class InventoryConflict(RuntimeError):
    pass


ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
MOVEMENT_TYPES = {
    'purchase_receive','sale_consume','sale_reversal','waste','manual_adjustment',
    'stock_count_adjustment','transfer'
}


def _now() -> int: return int(time.time()*1000)
def _actor_id(actor) -> str: return str(actor.get('id') or actor.get('username') or 'system')
def _d(v) -> Decimal:
    try: return Decimal(str(v))
    except (InvalidOperation,ValueError,TypeError) as exc: raise InventoryConflict('invalid decimal quantity') from exc

def _s(v: Decimal) -> str:
    # Preserve exact Decimal semantics without binary float conversion.
    return format(v, 'f')


def set_conversion(con: sqlite3.Connection, from_unit: str, to_unit: str, factor, dimension: str) -> None:
    ensure_phase3_schema(con)
    from_unit=str(from_unit).strip(); to_unit=str(to_unit).strip(); dimension=str(dimension).strip()
    f=_d(factor)
    if not from_unit or not to_unit or not dimension or f<=0: raise InventoryConflict('invalid conversion')
    con.execute('INSERT OR IGNORE INTO inventory_units(code,dimension) VALUES(?,?)',(from_unit,dimension))
    con.execute('INSERT OR IGNORE INTO inventory_units(code,dimension) VALUES(?,?)',(to_unit,dimension))
    d1=con.execute('SELECT dimension FROM inventory_units WHERE code=?',(from_unit,)).fetchone()['dimension']
    d2=con.execute('SELECT dimension FROM inventory_units WHERE code=?',(to_unit,)).fetchone()['dimension']
    if d1!=dimension or d2!=dimension: raise InventoryConflict('unit dimension mismatch')
    con.execute('''INSERT INTO unit_conversions(from_unit,to_unit,factor,dimension) VALUES(?,?,?,?)
                   ON CONFLICT(from_unit,to_unit) DO UPDATE SET factor=excluded.factor,dimension=excluded.dimension''',
                (from_unit,to_unit,_s(f),dimension))


def convert_quantity(con: sqlite3.Connection, quantity, from_unit: str, to_unit: str) -> Decimal:
    ensure_phase3_schema(con)
    q=_d(quantity); from_unit=str(from_unit); to_unit=str(to_unit)
    if from_unit==to_unit: return q
    u1=con.execute('SELECT dimension FROM inventory_units WHERE code=?',(from_unit,)).fetchone()
    u2=con.execute('SELECT dimension FROM inventory_units WHERE code=?',(to_unit,)).fetchone()
    if not u1 or not u2 or u1['dimension']!=u2['dimension']: raise InventoryConflict('incompatible units')
    direct=con.execute('SELECT factor FROM unit_conversions WHERE from_unit=? AND to_unit=?',(from_unit,to_unit)).fetchone()
    if direct: return q*_d(direct['factor'])
    reverse=con.execute('SELECT factor FROM unit_conversions WHERE from_unit=? AND to_unit=?',(to_unit,from_unit)).fetchone()
    if reverse: return q/_d(reverse['factor'])
    raise InventoryConflict('conversion not configured')


def create_inventory_item(con: sqlite3.Connection, item_id: str, name: str, base_unit: str, reorder_point, target_stock, actor: dict) -> dict:
    ensure_phase3_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise InventoryConflict('permission denied')
    item_id=str(item_id).strip(); name=str(name).strip(); base_unit=str(base_unit).strip()
    if not ID_RE.fullmatch(item_id) or len(name)<2 or len(name)>120: raise InventoryConflict('invalid inventory item')
    if not con.execute('SELECT 1 FROM inventory_units WHERE code=?',(base_unit,)).fetchone(): raise InventoryConflict('unknown base unit')
    rp=_d(reorder_point); ts=_d(target_stock)
    if rp<0 or ts<0 or ts<rp: raise InventoryConflict('invalid stock thresholds')
    con.execute('''INSERT INTO inventory_items(id,name,base_unit,reorder_point,target_stock,created_at,created_by)
                   VALUES(?,?,?,?,?,?,?)''',(item_id,name,base_unit,_s(rp),_s(ts),_now(),_actor_id(actor)))
    return dict(con.execute('SELECT * FROM inventory_items WHERE id=?',(item_id,)).fetchone())


def on_hand(con: sqlite3.Connection, item_id: str) -> Decimal:
    ensure_phase3_schema(con)
    if not con.execute('SELECT 1 FROM inventory_items WHERE id=?',(item_id,)).fetchone(): raise InventoryConflict('inventory item not found')
    total=Decimal('0')
    for row in con.execute('SELECT qty_base FROM stock_movements WHERE item_id=? ORDER BY id',(item_id,)):
        total += _d(row['qty_base'])
    return total


def append_movement(con: sqlite3.Connection, item_id: str, quantity, unit: str, movement_type: str, actor: dict, *, reason: str='', unit_cost=None, ref_type: str='', ref_id: str='', idempotency_key: str|None=None) -> dict:
    ensure_phase3_schema(con)
    item=con.execute('SELECT * FROM inventory_items WHERE id=?',(item_id,)).fetchone()
    if not item: raise InventoryConflict('inventory item not found')
    if movement_type not in MOVEMENT_TYPES: raise InventoryConflict('invalid movement type')
    base_qty=convert_quantity(con,_d(quantity),str(unit),item['base_unit'])
    if base_qty==0: raise InventoryConflict('zero movement')
    if movement_type in {'waste','sale_consume'} and base_qty>0: base_qty=-base_qty
    if movement_type in {'purchase_receive','sale_reversal'} and base_qty<0: base_qty=-base_qty
    if base_qty<0 and movement_type in {'manual_adjustment','stock_count_adjustment'} and len(str(reason).strip())<2:
        raise InventoryConflict('reason required')
    cost=None if unit_cost in (None,'') else _d(unit_cost)
    if cost is not None and cost<0: raise InventoryConflict('invalid unit cost')
    key = str(idempotency_key) if idempotency_key else None
    if key:
        old=con.execute('SELECT * FROM stock_movements WHERE idempotency_key=?',(key,)).fetchone()
        if old: return dict(old)
        cur=con.execute('''INSERT OR IGNORE INTO stock_movements(item_id,qty_base,movement_type,unit_cost,ref_type,ref_id,reason,actor_id,idempotency_key,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (item_id,_s(base_qty),movement_type,None if cost is None else _s(cost),str(ref_type),str(ref_id),str(reason),_actor_id(actor),key,_now()))
        if cur.rowcount == 0:
            old=con.execute('SELECT * FROM stock_movements WHERE idempotency_key=?',(key,)).fetchone()
            if old: return dict(old)
            raise InventoryConflict('idempotent stock movement unavailable')
    else:
        cur=con.execute('''INSERT INTO stock_movements(item_id,qty_base,movement_type,unit_cost,ref_type,ref_id,reason,actor_id,idempotency_key,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (item_id,_s(base_qty),movement_type,None if cost is None else _s(cost),str(ref_type),str(ref_id),str(reason),_actor_id(actor),None,_now()))
    return dict(con.execute('SELECT * FROM stock_movements WHERE id=?',(cur.lastrowid,)).fetchone())


def consume_order_items(con: sqlite3.Connection, order_id: str, trigger: str, actor: dict) -> list[dict]:
    ensure_phase3_schema(con)
    if trigger not in {'served','out_for_delivery','kitchen_send'}:
        raise InventoryConflict('invalid consumption trigger')
    began = not con.in_transaction
    try:
        if began:
            con.execute('BEGIN IMMEDIATE')
        if not con.execute('SELECT 1 FROM os_orders WHERE id=?',(order_id,)).fetchone():
            raise InventoryConflict('order not found')
        rows=con.execute('''SELECT oi.id AS order_item_id,oi.qty AS order_qty,rc.item_id,rc.qty_base,rc.base_unit,ii.weighted_avg_cost
                           FROM os_order_items oi
                           JOIN recipe_components rc ON rc.dish_id=oi.dish_id
                           JOIN inventory_items ii ON ii.id=rc.item_id
                           WHERE oi.order_id=? AND oi.status='active'
                           ORDER BY oi.id,rc.sort_order,rc.item_id''',(order_id,)).fetchall()
        out=[]
        for row in rows:
            quantity=_d(row['qty_base'])*Decimal(int(row['order_qty']))
            movement=append_movement(
                con,row['item_id'],quantity,row['base_unit'],'sale_consume',actor,
                reason=f'order consumption: {trigger}',unit_cost=(row['weighted_avg_cost'] or None),ref_type='order',ref_id=order_id,
                idempotency_key=f'sale:{order_id}:{row["order_item_id"]}:{row["item_id"]}',
            )
            out.append(movement)
        if began:
            con.commit()
        return out
    except Exception:
        if began and con.in_transaction:
            con.rollback()
        raise


def reverse_order_consumption(con: sqlite3.Connection, order_id: str, actor: dict, reason: str) -> list[dict]:
    ensure_phase3_schema(con)
    reason=str(reason or '').strip()
    if len(reason)<2:
        raise InventoryConflict('reversal reason required')
    began=not con.in_transaction
    try:
        if began:
            con.execute('BEGIN IMMEDIATE')
        consumed=con.execute('''SELECT sm.*,ii.base_unit FROM stock_movements sm
                                JOIN inventory_items ii ON ii.id=sm.item_id
                                WHERE sm.movement_type='sale_consume' AND sm.ref_type='order' AND sm.ref_id=?
                                ORDER BY sm.id''',(order_id,)).fetchall()
        out=[]
        for row in consumed:
            movement=append_movement(
                con,row['item_id'],abs(_d(row['qty_base'])),row['base_unit'],'sale_reversal',actor,
                reason=reason,unit_cost=row['unit_cost'],ref_type='order',ref_id=order_id,
                idempotency_key=f'sale-reversal:{row["id"]}',
            )
            out.append(movement)
        if began:
            con.commit()
        return out
    except Exception:
        if began and con.in_transaction:
            con.rollback()
        raise


def reserved_quantity(con: sqlite3.Connection, item_id: str) -> Decimal:
    ensure_phase3_schema(con)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='os_orders'").fetchone():
        return Decimal('0')
    total=Decimal('0')
    rows=con.execute('''SELECT oi.qty AS order_qty,rc.qty_base
                        FROM recipe_components rc
                        JOIN os_order_items oi ON oi.dish_id=rc.dish_id AND oi.status='active'
                        JOIN os_orders o ON o.id=oi.order_id
                        WHERE rc.item_id=? AND o.state IN ('open','confirmed','preparing','ready')''',(item_id,)).fetchall()
    for row in rows:
        total += _d(row['qty_base']) * Decimal(int(row['order_qty']))
    return total


def list_inventory_items(con: sqlite3.Connection) -> list[dict]:
    ensure_phase3_schema(con)
    out=[]
    for row in con.execute('SELECT * FROM inventory_items WHERE active=1 ORDER BY name,id'):
        item=dict(row)
        hand=on_hand(con,item['id']); reserved=reserved_quantity(con,item['id']); available=hand-reserved
        item.update(on_hand=_s(hand), reserved=_s(reserved), available=_s(available))
        out.append(item)
    return out


def low_stock_items(con: sqlite3.Connection) -> list[dict]:
    out=[]
    for item in list_inventory_items(con):
        if _d(item['available']) <= _d(item['reorder_point']):
            out.append({
                'item_id':item['id'],'name':item['name'],'base_unit':item['base_unit'],
                'on_hand':item['on_hand'],'reserved':item['reserved'],'available':item['available'],
                'reorder_point':item['reorder_point'],'target_stock':item['target_stock'],
            })
    return out


def record_waste(con: sqlite3.Connection, item_id: str, quantity, unit: str, actor: dict, *, reason: str) -> dict:
    ensure_phase3_schema(con)
    if actor.get('role') not in {'owner','manager'}:
        raise InventoryConflict('permission denied')
    reason=str(reason or '').strip()
    if len(reason)<2 or len(reason)>240:
        raise InventoryConflict('waste reason required')
    qty=_d(quantity)
    if qty<=0:
        raise InventoryConflict('waste quantity must be positive')
    began=not con.in_transaction
    try:
        if began: con.execute('BEGIN IMMEDIATE')
        ref_id='WASTE-'+secrets.token_hex(6).upper()
        movement=append_movement(con,item_id,qty,unit,'waste',actor,reason=reason,ref_type='waste',ref_id=ref_id)
        con.execute('''INSERT INTO waste_events(item_id,qty_base,reason,actor_id,movement_id,created_at)
                       VALUES(?,?,?,?,?,?)''',(item_id,movement['qty_base'],reason,_actor_id(actor),movement['id'],_now()))
        if began: con.commit()
        return movement
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise

def complete_stock_count(con: sqlite3.Connection, counts: list[dict], actor: dict, *, reason: str) -> dict:
    ensure_phase3_schema(con)
    if actor.get('role') not in {'owner','manager'}:
        raise InventoryConflict('permission denied')
    reason=str(reason or '').strip()
    if len(reason)<2 or len(reason)>240 or not isinstance(counts,list) or not counts:
        raise InventoryConflict('stock count reason and lines required')
    began=not con.in_transaction
    try:
        if began: con.execute('BEGIN IMMEDIATE')
        cur=con.execute('INSERT INTO stock_counts(actor_id,reason,created_at) VALUES(?,?,?)',(_actor_id(actor),reason,_now()))
        count_id=cur.lastrowid
        seen=set()
        for line in counts:
            item_id=str(line.get('item_id') or '').strip()
            if not item_id or item_id in seen: raise InventoryConflict('duplicate or missing count item')
            item=con.execute('SELECT base_unit FROM inventory_items WHERE id=? AND active=1',(item_id,)).fetchone()
            if not item: raise InventoryConflict('inventory item not found')
            counted=convert_quantity(con,_d(line.get('quantity')),str(line.get('unit') or ''),item['base_unit'])
            if counted<0: raise InventoryConflict('counted quantity cannot be negative')
            system=on_hand(con,item_id); variance=counted-system
            movement_id=None
            if variance!=0:
                movement=append_movement(con,item_id,variance,item['base_unit'],'stock_count_adjustment',actor,
                                         reason=reason,ref_type='stock_count',ref_id=str(count_id),
                                         idempotency_key=f'stock-count:{count_id}:{item_id}')
                movement_id=movement['id']
            con.execute('''INSERT INTO stock_count_lines(count_id,item_id,counted_qty_base,system_qty_base,variance_base,movement_id)
                           VALUES(?,?,?,?,?,?)''',(count_id,item_id,_s(counted),_s(system),_s(variance),movement_id))
            seen.add(item_id)
        if began: con.commit()
        return {'id':count_id,'line_count':len(seen),'reason':reason}
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise
