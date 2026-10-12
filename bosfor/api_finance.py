from __future__ import annotations

from .finance import close_cash_session, daily_close, open_cash_session, record_cash_adjustment, record_expense


def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')

def list_cash_sessions(con, actor):
    if actor.get('role') not in {'owner','manager','cashier'}: raise PermissionError('permission denied')
    if actor.get('role')=='cashier':
        rows=con.execute('''SELECT s.*,c.closed_at,c.expected_cash,c.counted_cash,c.variance FROM os_cash_sessions s
                            LEFT JOIN os_cash_closes c ON c.session_id=s.id WHERE s.cashier_id=? ORDER BY s.opened_at DESC LIMIT 200''',(_actor_id(actor),)).fetchall()
    else:
        rows=con.execute('''SELECT s.*,c.closed_at,c.expected_cash,c.counted_cash,c.variance FROM os_cash_sessions s
                            LEFT JOIN os_cash_closes c ON c.session_id=s.id ORDER BY s.opened_at DESC LIMIT 200''').fetchall()
    return [dict(r) for r in rows]

def list_expenses(con, actor):
    if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')
    return [dict(r) for r in con.execute('SELECT * FROM os_expenses ORDER BY created_at DESC,id DESC LIMIT 500')]

def finance_daily(con, actor, date):
    if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')
    return daily_close(con,date)

def handle_finance_action(con, action, payload, actor):
    if action in {'cash-open','cash-adjust','cash-close'} and actor.get('role') not in {'owner','manager','cashier'}:
        raise PermissionError('permission denied')
    if action=='expense' and actor.get('role') not in {'owner','manager'}:
        raise PermissionError('permission denied')
    if action=='cash-open':
        return 201,open_cash_session(con,actor,payload.get('opening_cash',0),payload.get('cashier_id'))
    if action=='cash-adjust':
        return 201,record_cash_adjustment(con,str(payload.get('session_id','')),actor,str(payload.get('kind','')),payload.get('amount'),str(payload.get('reason','')))
    if action=='cash-close':
        return 201,close_cash_session(con,str(payload.get('session_id','')),actor,payload.get('counted_cash'))
    if action=='expense':
        return 201,record_expense(con,actor,payload.get('amount'),str(payload.get('category','')),str(payload.get('reason','')))
    raise KeyError(action)
