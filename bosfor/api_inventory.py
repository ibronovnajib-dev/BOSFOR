from __future__ import annotations

from .inventory import (
    complete_stock_count, create_inventory_item, list_inventory_items,
    low_stock_items, record_waste,
)
from .recipes import recipe_cost, recipe_coverage, set_recipe


INVENTORY_ROLES={'owner','manager'}


def _need(actor):
    if actor.get('role') not in INVENTORY_ROLES:
        raise PermissionError('permission denied')


def list_items(con, actor):
    _need(actor)
    return list_inventory_items(con)


def list_low_stock(con, actor):
    _need(actor)
    return low_stock_items(con)


def get_recipe(con, dish_id: str, actor):
    _need(actor)
    dish_id=str(dish_id or '').strip()
    if not dish_id:
        raise ValueError('dish_id required')
    rows=con.execute('''SELECT rc.item_id,ii.name,rc.qty_base,rc.base_unit,rc.sort_order
                        FROM recipe_components rc JOIN inventory_items ii ON ii.id=rc.item_id
                        WHERE rc.dish_id=? ORDER BY rc.sort_order,rc.item_id''',(dish_id,)).fetchall()
    cost=recipe_cost(con,dish_id); coverage=recipe_coverage(con,dish_id)
    return {
        'dish_id':dish_id,
        'components':[dict(r) for r in rows],
        'cost':{
            'known_cost':str(cost.known_cost),
            'complete':cost.complete,
            'food_cost_percent':None if cost.food_cost_percent is None else str(cost.food_cost_percent),
            'coverage':str(coverage.ratio),
            'costed_components':coverage.costed_components,
            'total_components':coverage.total_components,
        },
    }


def handle_inventory_action(con, action: str, payload: dict, actor: dict):
    _need(actor)
    if action=='items':
        item=create_inventory_item(
            con,str(payload.get('id','')),str(payload.get('name','')),str(payload.get('base_unit','')),
            payload.get('reorder_point',0),payload.get('target_stock',0),actor,
        )
        return 201,item
    if action=='waste':
        movement=record_waste(con,str(payload.get('item_id','')),payload.get('quantity'),str(payload.get('unit','')),actor,reason=str(payload.get('reason','')))
        return 201,movement
    if action=='count':
        result=complete_stock_count(con,payload.get('counts'),actor,reason=str(payload.get('reason','')))
        return 201,result
    if action=='recipe':
        result=set_recipe(con,str(payload.get('dish_id','')),payload.get('components'),actor)
        return 200,result
    raise KeyError(action)
