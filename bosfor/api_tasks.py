from __future__ import annotations

from .tasks import add_logbook_entry, create_template, instantiate_checklist, overdue_tasks, transition_task

OPS_ROLES={'owner','manager','waiter','cashier','kitchen'}

def _actor_id(actor): return str(actor.get('id') or actor.get('username') or '')

def _need_ops(actor):
    if actor.get('role') not in OPS_ROLES: raise PermissionError('permission denied')

def _need_manager(actor):
    if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')

def list_tasks(con, actor):
    _need_ops(actor)
    if actor.get('role') in {'owner','manager'}:
        rows=con.execute('SELECT * FROM ops_tasks ORDER BY CASE status WHEN \'pending\' THEN 0 WHEN \'in_progress\' THEN 1 ELSE 2 END,due_at,id LIMIT 1000').fetchall()
    else:
        aid=_actor_id(actor)
        rows=con.execute("SELECT * FROM ops_tasks WHERE assigned_to='' OR assigned_to=? ORDER BY due_at,id LIMIT 500",(aid,)).fetchall()
    return [dict(r) for r in rows]

def list_overdue(con, actor):
    _need_ops(actor); rows=overdue_tasks(con)
    if actor.get('role') in {'owner','manager'}: return rows
    aid=_actor_id(actor); return [r for r in rows if not r.get('assigned_to') or r.get('assigned_to')==aid]

def list_templates(con, actor):
    _need_manager(actor)
    return [dict(r) for r in con.execute('SELECT * FROM ops_task_templates WHERE active=1 ORDER BY name,id')]

def list_logbook(con, actor):
    _need_manager(actor)
    return [dict(r) for r in con.execute('SELECT * FROM ops_logbook ORDER BY created_at DESC,id DESC LIMIT 500')]

def handle_task_action(con, action, payload, actor):
    _need_ops(actor)
    if action=='template':
        _need_manager(actor); return 201,create_template(con,str(payload.get('name','')),payload.get('items'),actor)
    if action=='instantiate':
        _need_manager(actor); return 201,instantiate_checklist(con,str(payload.get('template_id','')),str(payload.get('business_date','')),actor,str(payload.get('assigned_to','')))
    if action=='state':
        return 200,transition_task(con,int(payload.get('task_id')),str(payload.get('state','')),actor,str(payload.get('reason','')))
    if action=='logbook':
        _need_manager(actor); return 201,add_logbook_entry(con,str(payload.get('entry','')),actor,related_type=str(payload.get('related_type','')),related_id=str(payload.get('related_id','')))
    raise KeyError(action)
