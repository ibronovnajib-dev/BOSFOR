from __future__ import annotations

import re
import secrets
import sqlite3
import time
from decimal import Decimal

from .inventory import InventoryConflict, _d, _s, append_movement, convert_quantity, low_stock_items, on_hand
from .migrations import ensure_phase3_schema


class PurchasingConflict(RuntimeError):
    pass


def _now(): return int(time.time()*1000)
def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')
def _need(actor):
    if actor.get('role') not in {'owner','manager'}: raise PurchasingConflict('permission denied')


def create_supplier(con: sqlite3.Connection, name: str, actor: dict, *, phone: str='', email: str='') -> dict:
    ensure_phase3_schema(con); _need(actor)
    name=str(name or '').strip(); phone=str(phone or '').strip(); email=str(email or '').strip()
    if len(name)<2 or len(name)>120 or len(phone)>40 or len(email)>160: raise PurchasingConflict('invalid supplier')
    sid='SUP-'+secrets.token_hex(5).upper()
    con.execute('INSERT INTO suppliers(id,name,phone,email,active,created_at,created_by) VALUES(?,?,?,?,1,?,?)',
                (sid,name,phone,email,_now(),_actor_id(actor)))
    return dict(con.execute('SELECT * FROM suppliers WHERE id=?',(sid,)).fetchone())


def _po(con, po_id: str) -> dict:
    row=con.execute('SELECT * FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
    if not row: raise PurchasingConflict('purchase order not found')
    out=dict(row)
    out['lines']=[dict(r) for r in con.execute('SELECT * FROM purchase_order_lines WHERE po_id=? ORDER BY id',(po_id,))]
    return out


def create_purchase_order(con: sqlite3.Connection, supplier_id: str, lines: list[dict], actor: dict, note: str='') -> dict:
    ensure_phase3_schema(con); _need(actor)
    supplier=con.execute('SELECT id FROM suppliers WHERE id=? AND active=1',(str(supplier_id),)).fetchone()
    if not supplier or not isinstance(lines,list) or not lines: raise PurchasingConflict('supplier and lines required')
    normalized=[]
    for line in lines:
        item_id=str(line.get('item_id') or '').strip()
        item=con.execute('SELECT base_unit FROM inventory_items WHERE id=? AND active=1',(item_id,)).fetchone()
        if not item: raise PurchasingConflict('inventory item not found')
        qty=convert_quantity(con,_d(line.get('quantity')),str(line.get('unit') or ''),item['base_unit'])
        cost=_d(line.get('unit_cost'))
        if qty<=0 or cost<0: raise PurchasingConflict('invalid purchase line')
        normalized.append((item_id,_s(qty),item['base_unit'],_s(cost)))
    po_id='PO-'+secrets.token_hex(6).upper(); began=not con.in_transaction
    try:
        if began: con.execute('BEGIN IMMEDIATE')
        con.execute('INSERT INTO purchase_orders(id,supplier_id,status,note,created_by,created_at) VALUES(?,?,\'draft\',?,?,?)',
                    (po_id,supplier_id,str(note or '')[:300],_actor_id(actor),_now()))
        con.executemany('INSERT INTO purchase_order_lines(po_id,item_id,ordered_qty_base,base_unit,unit_cost) VALUES(?,?,?,?,?)',
                        [(po_id,*x) for x in normalized])
        if began: con.commit()
        return _po(con,po_id)
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def approve_po(con: sqlite3.Connection, po_id: str, actor: dict) -> dict:
    ensure_phase3_schema(con); _need(actor)
    po=_po(con,po_id)
    if po['status']=='approved': return po
    if po['status']!='draft': raise PurchasingConflict('only draft PO can be approved')
    con.execute("UPDATE purchase_orders SET status='approved',approved_by=?,approved_at=? WHERE id=?",(_actor_id(actor),_now(),po_id))
    return _po(con,po_id)


def _historical_weighted_cost(con: sqlite3.Connection, item_id: str) -> Decimal | None:
    qty=Decimal('0'); value=Decimal('0')
    for row in con.execute("SELECT qty_base,unit_cost FROM stock_movements WHERE item_id=? AND movement_type='purchase_receive' AND unit_cost IS NOT NULL",(item_id,)):
        q=_d(row['qty_base'])
        if q<=0: continue
        qty+=q; value+=q*_d(row['unit_cost'])
    return None if qty==0 else value/qty


def _receipt(con, receipt_id: str) -> dict:
    row=con.execute('SELECT * FROM goods_receipts WHERE id=?',(receipt_id,)).fetchone()
    if not row: raise PurchasingConflict('receipt not found')
    out=dict(row); out['lines']=[dict(r) for r in con.execute('SELECT * FROM goods_receipt_lines WHERE receipt_id=? ORDER BY po_line_id',(receipt_id,))]
    out['po_status']=con.execute('SELECT status FROM purchase_orders WHERE id=?',(out['po_id'],)).fetchone()['status']
    return out


def receive_po(con: sqlite3.Connection, po_id: str, lines: list[dict], actor: dict, idempotency_key: str) -> dict:
    ensure_phase3_schema(con); _need(actor)
    key=str(idempotency_key or '').strip()
    if len(key)<4 or len(key)>100 or not isinstance(lines,list) or not lines: raise PurchasingConflict('valid idempotency key and lines required')
    old=con.execute('SELECT id FROM goods_receipts WHERE idempotency_key=?',(key,)).fetchone()
    if old: return _receipt(con,old['id'])
    began=not con.in_transaction
    try:
        if began: con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT id FROM goods_receipts WHERE idempotency_key=?',(key,)).fetchone()
        if old:
            if began: con.commit()
            return _receipt(con,old['id'])
        po=con.execute('SELECT * FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
        if not po: raise PurchasingConflict('purchase order not found')
        if po['status'] not in {'approved','partial'}: raise PurchasingConflict('purchase order is not receivable')
        rid='GR-'+secrets.token_hex(6).upper()
        con.execute('INSERT INTO goods_receipts(id,po_id,idempotency_key,actor_id,created_at) VALUES(?,?,?,?,?)',(rid,po_id,key,_actor_id(actor),_now()))
        seen=set()
        for incoming in lines:
            line_id=int(incoming.get('line_id') or 0)
            if line_id in seen: raise PurchasingConflict('duplicate receipt line')
            line=con.execute('SELECT * FROM purchase_order_lines WHERE id=? AND po_id=?',(line_id,po_id)).fetchone()
            if not line: raise PurchasingConflict('purchase line not found')
            qty=convert_quantity(con,_d(incoming.get('quantity')),str(incoming.get('unit') or line['base_unit']),line['base_unit'])
            if qty<=0: raise PurchasingConflict('receive quantity must be positive')
            cost=_d(incoming.get('unit_cost') if incoming.get('unit_cost') not in (None,'') else line['unit_cost'])
            if cost<0: raise PurchasingConflict('invalid receive cost')
            already=_d(line['received_qty_base']); ordered=_d(line['ordered_qty_base'])
            # Over-receipt is a manager/owner-only action; _need above enforces that permission.
            new_received=already+qty
            old_hand=on_hand(con,line['item_id'])
            movement=append_movement(con,line['item_id'],qty,line['base_unit'],'purchase_receive',actor,unit_cost=cost,
                                     reason=f'goods receipt {rid}',ref_type='goods_receipt',ref_id=rid,
                                     idempotency_key=f'goods-receipt:{rid}:{line_id}')
            con.execute('UPDATE purchase_order_lines SET received_qty_base=? WHERE id=?',(_s(new_received),line_id))
            con.execute('''INSERT INTO goods_receipt_lines(receipt_id,po_line_id,qty_base,unit_cost,movement_id)
                           VALUES(?,?,?,?,?)''',(rid,line_id,_s(qty),_s(cost),movement['id']))
            avg=_historical_weighted_cost(con,line['item_id'])
            if avg is not None:
                con.execute('UPDATE inventory_items SET weighted_avg_cost=? WHERE id=?',(_s(avg),line['item_id']))
            con.execute('''INSERT INTO supplier_items(supplier_id,item_id,last_cost) VALUES(?,?,?)
                           ON CONFLICT(supplier_id,item_id) DO UPDATE SET last_cost=excluded.last_cost''',(po['supplier_id'],line['item_id'],_s(cost)))
            seen.add(line_id)
        po_lines=con.execute('SELECT ordered_qty_base,received_qty_base FROM purchase_order_lines WHERE po_id=?',(po_id,)).fetchall()
        remaining=sum(1 for row in po_lines if _d(row['received_qty_base']) < _d(row['ordered_qty_base']))
        status='partial' if remaining else 'received'
        con.execute('UPDATE purchase_orders SET status=? WHERE id=?',(status,po_id))
        if began: con.commit()
        return _receipt(con,rid)
    except sqlite3.IntegrityError as exc:
        if began and con.in_transaction: con.rollback()
        old=con.execute('SELECT id FROM goods_receipts WHERE idempotency_key=?',(key,)).fetchone()
        if old: return _receipt(con,old['id'])
        raise PurchasingConflict('receiving conflict') from exc
    except (InventoryConflict, ValueError, TypeError) as exc:
        if began and con.in_transaction: con.rollback()
        raise PurchasingConflict(str(exc)) from exc
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def suggest_reorder(con: sqlite3.Connection) -> list[dict]:
    ensure_phase3_schema(con)
    out=[]
    for item in low_stock_items(con):
        qty=_d(item['target_stock'])-_d(item['available'])
        if qty>0:
            out.append({'item_id':item['item_id'],'name':item['name'],'base_unit':item['base_unit'],
                        'available':item['available'],'target_stock':item['target_stock'],'suggested_qty':_s(qty)})
    return out
