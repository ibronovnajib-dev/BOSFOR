from __future__ import annotations

from .purchasing import approve_po, create_purchase_order, create_supplier, receive_po, suggest_reorder

ROLES={'owner','manager'}

def _need(actor):
    if actor.get('role') not in ROLES: raise PermissionError('permission denied')

def list_suppliers(con,actor):
    _need(actor)
    return [dict(r) for r in con.execute('SELECT * FROM suppliers WHERE active=1 ORDER BY name,id')]

def list_orders(con,actor):
    _need(actor); out=[]
    rows=con.execute('''SELECT po.*,s.name supplier_name FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id
                        ORDER BY po.created_at DESC,po.id DESC LIMIT 500''').fetchall()
    for row in rows:
        po=dict(row); po['lines']=[dict(x) for x in con.execute('''SELECT pol.*,ii.name item_name FROM purchase_order_lines pol
                                                                   JOIN inventory_items ii ON ii.id=pol.item_id
                                                                   WHERE po_id=? ORDER BY pol.id''',(po['id'],))]
        out.append(po)
    return out

def list_suggestions(con,actor):
    _need(actor); return suggest_reorder(con)

def handle_purchasing_action(con,action,payload,actor,idempotency_key=''):
    _need(actor)
    if action=='suppliers':
        return 201,create_supplier(con,str(payload.get('name','')),actor,phone=str(payload.get('phone','')),email=str(payload.get('email','')))
    if action=='orders':
        return 201,create_purchase_order(con,str(payload.get('supplier_id','')),payload.get('lines'),actor,str(payload.get('note','')))
    if action=='approve':
        return 200,approve_po(con,str(payload.get('po_id','')),actor)
    if action=='receive':
        return 201,receive_po(con,str(payload.get('po_id','')),payload.get('lines'),actor,idempotency_key)
    raise KeyError(action)
