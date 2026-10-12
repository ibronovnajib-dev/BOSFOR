from __future__ import annotations

import secrets

from .crm import (
    add_customer_note, add_customer_tag, customer_profile, earn_points,
    get_or_create_customer, loyalty_balance, redeem_points,
)

MANAGER_ROLES={'owner','manager'}

def _need_manager(actor):
    if actor.get('role') not in MANAGER_ROLES: raise PermissionError('permission denied')

def get_profile(con, phone, actor):
    _need_manager(actor)
    out=customer_profile(con,phone,include_private=True)
    out['loyalty_balance']=loyalty_balance(con,phone)
    return out

def list_customers(con, actor):
    _need_manager(actor)
    rows=con.execute('SELECT phone,name,visits,lifetime_spend,last_visit_ts,updated_at FROM crm_customers ORDER BY last_visit_ts DESC,updated_at DESC LIMIT 1000').fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['loyalty_balance']=loyalty_balance(con,d['phone']); out.append(d)
    return out

def handle_crm_action(con, action, payload, actor, idempotency_key=''):
    _need_manager(actor)
    phone=str(payload.get('phone',''))
    if action=='customer':
        return 201,get_or_create_customer(con,phone,str(payload.get('name','')),actor)
    if action=='tag':
        return 201,add_customer_tag(con,phone,str(payload.get('tag','')),actor)
    if action=='note':
        return 201,add_customer_note(con,phone,str(payload.get('note','')),actor)
    if action in {'earn','redeem'}:
        key=str(idempotency_key or payload.get('idempotency_key') or f"crm-{action}-{secrets.token_urlsafe(12)}")
        fn=earn_points if action=='earn' else redeem_points
        event=fn(con,phone,payload.get('points'),actor,key,str(payload.get('reason','')))
        return 201,{'event':event,'loyalty_balance':loyalty_balance(con,phone)}
    raise KeyError(action)
