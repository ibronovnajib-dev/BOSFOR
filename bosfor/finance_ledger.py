from __future__ import annotations

import sqlite3
import time
from .migrations import ensure_phase2_schema
from .orders import recalculate_order


class LedgerConflict(RuntimeError):
    pass


def _now(): return int(time.time()*1000)

def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')

def _row(con, pid):
    r=con.execute('SELECT * FROM os_payments WHERE id=?',(pid,)).fetchone()
    return dict(r) if r else None


def payment_balance(con: sqlite3.Connection, order_id: str) -> dict:
    ensure_phase2_schema(con)
    order=con.execute('SELECT total FROM os_orders WHERE id=?',(order_id,)).fetchone()
    if not order: raise LedgerConflict('order not found')
    sums=con.execute('''SELECT
      COALESCE(SUM(CASE WHEN direction='payment' THEN amount ELSE 0 END),0) paid,
      COALESCE(SUM(CASE WHEN direction='refund' THEN amount ELSE 0 END),0) refunded
      FROM os_payments WHERE order_id=?''',(order_id,)).fetchone()
    total=int(order['total']); paid=int(sums['paid']); refunded=int(sums['refunded'])
    net=max(0, paid-refunded); due=max(0,total-net)
    return {'total':total,'paid':paid,'refunded':refunded,'net_paid':net,'due':due}


def record_payment(con, order_id, actor, method, amount, idempotency_key):
    ensure_phase2_schema(con)
    if method not in {'cash','card','qr','wallet'}: raise LedgerConflict('invalid method')
    try: amount=int(amount)
    except Exception: raise LedgerConflict('invalid amount')
    if amount<=0: raise LedgerConflict('invalid amount')
    key=str(idempotency_key or '').strip()
    if not key: raise LedgerConflict('idempotency key required')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        old=con.execute('SELECT id FROM os_payments WHERE idempotency_key=?',(key,)).fetchone()
        if old:
            result=_row(con,old['id'])
            if began: con.commit()
            return result
        order=con.execute('SELECT state FROM os_orders WHERE id=?',(order_id,)).fetchone()
        if not order or order['state'] in {'closed','cancelled'}: raise LedgerConflict('order not payable')
        bal=payment_balance(con,order_id)
        if amount>bal['due']: raise LedgerConflict('payment exceeds due')
        cur=con.execute('''INSERT INTO os_payments(order_id,actor_id,method,amount,direction,idempotency_key,created_at)
          VALUES(?,?,?,?, 'payment', ?,?)''',(order_id,_actor_id(actor),method,amount,key,_now()))
        result=_row(con,cur.lastrowid)
        if began: con.commit()
        return result
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise LedgerConflict('payment busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def apply_discount(con, order_id, actor, kind, value, reason):
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise LedgerConflict('permission denied')
    if kind not in {'percent','fixed'}: raise LedgerConflict('invalid discount kind')
    try: value=int(value)
    except Exception: raise LedgerConflict('invalid discount value')
    if value<=0 or (kind=='percent' and value>100): raise LedgerConflict('invalid discount value')
    reason=str(reason or '').strip()
    if len(reason)<2: raise LedgerConflict('reason required')
    totals=recalculate_order(con,order_id)
    amount=(totals['subtotal']*value//100) if kind=='percent' else min(value,totals['subtotal'])
    cur=con.execute('''INSERT INTO os_order_adjustments(order_id,actor_id,kind,value,amount,reason,created_at)
      VALUES(?,?,?,?,?,?,?)''',(order_id,_actor_id(actor),kind,value,amount,reason,_now()))
    recalculate_order(con,order_id)
    r=con.execute('SELECT * FROM os_order_adjustments WHERE id=?',(cur.lastrowid,)).fetchone()
    return dict(r)


def refund_payment(con, payment_id, actor, amount, reason):
    ensure_phase2_schema(con)
    if actor.get('role') not in {'owner','manager','cashier'}: raise LedgerConflict('permission denied')
    try: amount=int(amount)
    except Exception: raise LedgerConflict('invalid amount')
    if amount<=0: raise LedgerConflict('invalid amount')
    reason=str(reason or '').strip()
    if len(reason)<2: raise LedgerConflict('reason required')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        p=con.execute("SELECT * FROM os_payments WHERE id=? AND direction='payment'",(payment_id,)).fetchone()
        if not p: raise LedgerConflict('payment not found')
        refunded=int(con.execute("SELECT COALESCE(SUM(amount),0) v FROM os_payments WHERE parent_payment_id=? AND direction='refund'",(payment_id,)).fetchone()['v'])
        if refunded+amount>int(p['amount']): raise LedgerConflict('refund exceeds payment')
        key=f'refund:{payment_id}:{_now()}:{amount}'
        cur=con.execute('''INSERT INTO os_payments(order_id,actor_id,method,amount,direction,parent_payment_id,reason,idempotency_key,created_at)
          VALUES(?,?,?,?, 'refund', ?,?,?,?)''',(p['order_id'],_actor_id(actor),p['method'],amount,payment_id,reason,key,_now()))
        result=_row(con,cur.lastrowid)
        if began: con.commit()
        return result
    except sqlite3.OperationalError as exc:
        if began and con.in_transaction: con.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower(): raise LedgerConflict('refund busy') from exc
        raise
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise
