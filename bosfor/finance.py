from __future__ import annotations

import secrets
import sqlite3
import time

from .migrations import ensure_phase2_schema, ensure_phase4_schema


class CashConflict(RuntimeError):
    pass


def _now() -> int:
    return int(time.time()*1000)


def _actor_id(actor: dict) -> str:
    return str(actor.get('id') or actor.get('username') or 'system')


def _session(con: sqlite3.Connection, session_id: str):
    row=con.execute('SELECT * FROM os_cash_sessions WHERE id=?',(session_id,)).fetchone()
    if not row: raise CashConflict('cash session not found')
    return dict(row)


def _closed(con: sqlite3.Connection, session_id: str):
    row=con.execute('SELECT * FROM os_cash_closes WHERE session_id=?',(session_id,)).fetchone()
    return dict(row) if row else None


def open_cash_session(con: sqlite3.Connection, actor: dict, opening_cash: int, cashier_id: str | None=None) -> dict:
    ensure_phase2_schema(con); ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager','cashier'}: raise CashConflict('permission denied')
    cashier_id=str(cashier_id or _actor_id(actor)).strip()
    if actor.get('role')=='cashier' and cashier_id != _actor_id(actor): raise CashConflict('permission denied')
    try: opening_cash=int(opening_cash)
    except Exception: raise CashConflict('invalid opening cash')
    if opening_cash<0: raise CashConflict('invalid opening cash')
    existing=con.execute('''SELECT s.id FROM os_cash_sessions s LEFT JOIN os_cash_closes c ON c.session_id=s.id
                            WHERE s.cashier_id=? AND c.session_id IS NULL ORDER BY s.opened_at DESC LIMIT 1''',(cashier_id,)).fetchone()
    if existing: raise CashConflict('cash session already open')
    sid='CS-'+secrets.token_hex(5).upper(); now=_now()
    con.execute('INSERT INTO os_cash_sessions(id,cashier_id,opening_cash,opened_at,opened_by) VALUES(?,?,?,?,?)',(sid,cashier_id,opening_cash,now,_actor_id(actor)))
    return _session(con,sid)


def record_cash_adjustment(con: sqlite3.Connection, session_id: str, actor: dict, kind: str, amount: int, reason: str) -> dict:
    ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager','cashier'}: raise CashConflict('permission denied')
    session=_session(con,session_id)
    if _closed(con,session_id): raise CashConflict('cash session closed')
    if actor.get('role')=='cashier' and session['cashier_id'] != _actor_id(actor): raise CashConflict('permission denied')
    if kind not in {'cash_in','cash_out'}: raise CashConflict('invalid adjustment kind')
    try: amount=int(amount)
    except Exception: raise CashConflict('invalid amount')
    reason=str(reason or '').strip()
    if amount<=0 or len(reason)<2: raise CashConflict('reason and positive amount required')
    cur=con.execute('INSERT INTO os_cash_adjustments(session_id,actor_id,kind,amount,reason,created_at) VALUES(?,?,?,?,?,?)',(session_id,_actor_id(actor),kind,amount,reason,_now()))
    return dict(con.execute('SELECT * FROM os_cash_adjustments WHERE id=?',(cur.lastrowid,)).fetchone())


def expected_cash(con: sqlite3.Connection, session_id: str, *, until: int | None=None) -> int:
    ensure_phase2_schema(con); ensure_phase4_schema(con)
    s=_session(con,session_id); end=_now() if until is None else int(until)
    pay=con.execute('''SELECT COALESCE(SUM(CASE WHEN direction='payment' THEN amount ELSE -amount END),0) v
                       FROM os_payments WHERE actor_id=? AND method='cash' AND created_at>=? AND created_at<=?''',(s['cashier_id'],s['opened_at'],end)).fetchone()['v']
    adj=con.execute("SELECT COALESCE(SUM(CASE WHEN kind='cash_in' THEN amount ELSE -amount END),0) v FROM os_cash_adjustments WHERE session_id=? AND created_at<=?",(session_id,end)).fetchone()['v']
    return int(s['opening_cash'])+int(pay)+int(adj)


def close_cash_session(con: sqlite3.Connection, session_id: str, actor: dict, counted_cash: int) -> dict:
    ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager','cashier'}: raise CashConflict('permission denied')
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        s=_session(con,session_id)
        if _closed(con,session_id): raise CashConflict('cash session already closed')
        if actor.get('role')=='cashier' and s['cashier_id'] != _actor_id(actor): raise CashConflict('permission denied')
        try: counted_cash=int(counted_cash)
        except Exception: raise CashConflict('invalid counted cash')
        if counted_cash<0: raise CashConflict('invalid counted cash')
        closed_at=_now(); expected=expected_cash(con,session_id,until=closed_at); variance=counted_cash-expected
        con.execute('INSERT INTO os_cash_closes(session_id,closed_by,closed_at,expected_cash,counted_cash,variance) VALUES(?,?,?,?,?,?)',(session_id,_actor_id(actor),closed_at,expected,counted_cash,variance))
        if began: con.commit()
        return _closed(con,session_id)
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise


def record_expense(con: sqlite3.Connection, actor: dict, amount: int, category: str, reason: str) -> dict:
    ensure_phase4_schema(con)
    if actor.get('role') not in {'owner','manager'}: raise CashConflict('permission denied')
    try: amount=int(amount)
    except Exception: raise CashConflict('invalid expense amount')
    category=str(category or '').strip(); reason=str(reason or '').strip()
    if amount<=0 or len(category)<2 or len(category)>80 or len(reason)<2 or len(reason)>240:
        raise CashConflict('invalid expense')
    cur=con.execute('INSERT INTO os_expenses(actor_id,amount,category,reason,created_at) VALUES(?,?,?,?,?)',(_actor_id(actor),amount,category,reason,_now()))
    return dict(con.execute('SELECT * FROM os_expenses WHERE id=?',(cur.lastrowid,)).fetchone())


def _business_bounds(business_date: str) -> tuple[int,int]:
    from datetime import datetime, timezone, timedelta
    try:
        d=datetime.strptime(str(business_date),'%Y-%m-%d').date()
    except Exception as exc:
        raise CashConflict('invalid business date') from exc
    tz=timezone(timedelta(hours=5))
    start=datetime(d.year,d.month,d.day,tzinfo=tz)
    end=start+timedelta(days=1)
    return int(start.timestamp()*1000), int(end.timestamp()*1000)


def daily_close(con: sqlite3.Connection, business_date: str) -> dict:
    from decimal import Decimal
    ensure_phase2_schema(con); ensure_phase4_schema(con)
    start,end=_business_bounds(business_date)
    orders=con.execute('''SELECT id,subtotal,discount_total,total FROM os_orders
                          WHERE state='closed' AND closed_at>=? AND closed_at<? ORDER BY closed_at,id''',(start,end)).fetchall()
    gross=sum(int(r['subtotal']) for r in orders); discounts=sum(int(r['discount_total']) for r in orders); net_sales=sum(int(r['total']) for r in orders)
    payment_rows=con.execute('''SELECT method,direction,amount FROM os_payments WHERE created_at>=? AND created_at<?''',(start,end)).fetchall()
    methods={'cash':0,'card':0,'qr':0,'wallet':0}; refunds=0; paid=0
    for r in payment_rows:
        amount=int(r['amount'])
        if r['direction']=='refund':
            refunds += amount; methods[r['method']]=methods.get(r['method'],0)-amount
        else:
            paid += amount; methods[r['method']]=methods.get(r['method'],0)+amount
    expense_total=int(con.execute('SELECT COALESCE(SUM(amount),0) v FROM os_expenses WHERE created_at>=? AND created_at<?',(start,end)).fetchone()['v'])
    # Consumption cost is snapshotted at the time of movement. Reversal rows subtract that same historical cost.
    cogs=Decimal('0'); total_cost_rows=0; known_cost_rows=0
    for r in con.execute("SELECT movement_type,qty_base,unit_cost FROM stock_movements WHERE movement_type IN ('sale_consume','sale_reversal') AND created_at>=? AND created_at<?",(start,end)):
        total_cost_rows += 1
        if r['unit_cost'] in (None,''):
            continue
        known_cost_rows += 1
        value=abs(Decimal(str(r['qty_base'])))*Decimal(str(r['unit_cost']))
        cogs += -value if r['movement_type']=='sale_reversal' else value
    coverage=1.0 if total_cost_rows==0 else known_cost_rows/total_cost_rows
    complete=(total_cost_rows==0 or known_cost_rows==total_cost_rows)
    variance=int(con.execute('SELECT COALESCE(SUM(variance),0) v FROM os_cash_closes WHERE closed_at>=? AND closed_at<?',(start,end)).fetchone()['v'])
    warnings=[]
    if variance: warnings.append(f'Cash variance: {variance}')
    if not complete: warnings.append('COGS estimate is incomplete because some stock movements have no cost snapshot')
    gp=(Decimal(net_sales)-cogs) if complete else None
    op=(gp-Decimal(expense_total)) if gp is not None else None
    return {
        'business_date':str(business_date),'orders_count':len(orders),'gross_sales':gross,'discounts':discounts,'net_sales':net_sales,
        'refunds':refunds,'payments':methods,'net_collected':paid-refunds,'average_check':0 if not orders else round(net_sales/len(orders),2),
        'expenses':expense_total,'cogs_estimate':format(cogs,'f'),'cogs_complete':complete,'cogs_coverage':coverage,
        'gross_profit_estimate':None if gp is None else format(gp,'f'),'operating_result_estimate':None if op is None else format(op,'f'),
        'cash_variance_total':variance,'warnings':warnings,
    }
