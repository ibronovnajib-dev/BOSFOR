from __future__ import annotations

from .kitchen import list_tickets, set_dish_availability, set_ticket_state

READ_ROLES={'owner','manager','kitchen'}
WRITE_ROLES={'owner','manager','kitchen'}


def _need(actor, roles):
    if actor.get('role') not in roles:
        raise PermissionError('permission denied')


def get_tickets(con, actor):
    _need(actor, READ_ROLES)
    return list_tickets(con, actor, active_only=True)


def handle_kitchen_action(con, action, payload, actor):
    _need(actor, WRITE_ROLES)
    if action=='state':
        return 200, set_ticket_state(con, int(payload.get('ticket_id',0)), str(payload.get('target','')), actor)
    if action=='availability':
        set_dish_availability(con, str(payload.get('dish_id','')), bool(payload.get('available')), actor, str(payload.get('reason','')))
        return 200, {'dish_id':str(payload.get('dish_id','')), 'available':bool(payload.get('available'))}
    raise KeyError(action)
