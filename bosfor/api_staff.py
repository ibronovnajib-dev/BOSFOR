from __future__ import annotations

from .staff import schedule_shift, clock_in, clock_out, correct_clock_event, hours_summary


def _actor_id(actor): return str(actor.get('id') or actor.get('username') or 'system')

def list_shifts(con, actor, staff_id=''):
    if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')
    if staff_id:
        rows=con.execute('SELECT * FROM os_staff_shifts WHERE staff_id=? ORDER BY start_at DESC LIMIT 500',(staff_id,)).fetchall()
    else:
        rows=con.execute('SELECT * FROM os_staff_shifts ORDER BY start_at DESC LIMIT 500').fetchall()
    return [dict(r) for r in rows]

def staff_summary(con, actor, staff_id, start_at, end_at):
    if actor.get('role') not in {'owner','manager'} and str(staff_id)!=_actor_id(actor): raise PermissionError('permission denied')
    return hours_summary(con,str(staff_id),int(start_at),int(end_at))

def handle_staff_action(con, action, payload, actor):
    if action=='shift':
        if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')
        return 201,schedule_shift(con,str(payload.get('staff_id','')),payload.get('start_at'),payload.get('end_at'),actor,note=str(payload.get('note','')))
    if action=='clock-in':
        staff_id=str(payload.get('staff_id') or _actor_id(actor))
        if actor.get('role') not in {'owner','manager'}: staff_id=_actor_id(actor)
        return 201,clock_in(con,staff_id,actor,at=payload.get('at'))
    if action=='clock-out':
        staff_id=str(payload.get('staff_id') or _actor_id(actor))
        if actor.get('role') not in {'owner','manager'}: staff_id=_actor_id(actor)
        return 201,clock_out(con,staff_id,actor,at=payload.get('at'))
    if action=='correct':
        if actor.get('role') not in {'owner','manager'}: raise PermissionError('permission denied')
        return 201,correct_clock_event(con,int(payload.get('event_id')),int(payload.get('corrected_at')),actor,str(payload.get('reason','')))
    raise KeyError(action)
