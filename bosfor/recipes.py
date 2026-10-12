from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal

from .inventory import InventoryConflict, _d, _s, convert_quantity
from .migrations import ensure_phase3_schema


@dataclass(frozen=True)
class Coverage:
    total_components: int
    costed_components: int
    ratio: Decimal


@dataclass(frozen=True)
class RecipeCost:
    dish_id: str
    known_cost: Decimal
    complete: bool
    food_cost_percent: Decimal | None


def _actor_id(actor: dict) -> str:
    return str(actor.get('id') or actor.get('username') or 'system')


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _item_unit_cost(con: sqlite3.Connection, item_id: str) -> Decimal | None:
    row = con.execute('SELECT weighted_avg_cost FROM inventory_items WHERE id=?', (item_id,)).fetchone()
    if not row:
        return None
    raw = str(row['weighted_avg_cost'] or '').strip()
    if raw:
        return _d(raw)
    total_qty = Decimal('0')
    total_value = Decimal('0')
    for movement in con.execute(
        "SELECT qty_base,unit_cost FROM stock_movements WHERE item_id=? AND movement_type='purchase_receive' AND unit_cost IS NOT NULL",
        (item_id,),
    ):
        qty = _d(movement['qty_base'])
        if qty <= 0:
            continue
        total_qty += qty
        total_value += qty * _d(movement['unit_cost'])
    return None if total_qty == 0 else total_value / total_qty


def set_recipe(con: sqlite3.Connection, dish_id: str, components: list[dict], actor: dict) -> dict:
    ensure_phase3_schema(con)
    if actor.get('role') not in {'owner', 'manager'}:
        raise InventoryConflict('permission denied')
    dish_id = str(dish_id).strip()
    if not dish_id or not isinstance(components, list) or not components:
        raise InventoryConflict('recipe requires components')
    if _table_exists(con, 'dishes') and not con.execute('SELECT 1 FROM dishes WHERE id=?', (dish_id,)).fetchone():
        raise InventoryConflict('dish not found')

    normalized: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    for idx, component in enumerate(components):
        item_id = str(component.get('item_id') or '').strip()
        if not item_id or item_id in seen:
            raise InventoryConflict('duplicate or missing recipe item')
        item = con.execute('SELECT base_unit FROM inventory_items WHERE id=? AND active=1', (item_id,)).fetchone()
        if not item:
            raise InventoryConflict('inventory item not found')
        qty = _d(component.get('quantity'))
        if qty <= 0:
            raise InventoryConflict('recipe quantity must be positive')
        base_qty = convert_quantity(con, qty, str(component.get('unit') or ''), item['base_unit'])
        if base_qty <= 0:
            raise InventoryConflict('recipe quantity must be positive')
        normalized.append((item_id, _s(base_qty), item['base_unit'], idx))
        seen.add(item_id)

    began = not con.in_transaction
    if began:
        con.execute('BEGIN IMMEDIATE')
    try:
        con.execute(
            '''INSERT INTO recipes(dish_id,updated_at,updated_by) VALUES(?,?,?)
               ON CONFLICT(dish_id) DO UPDATE SET updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
            (dish_id, int(time.time() * 1000), _actor_id(actor)),
        )
        con.execute('DELETE FROM recipe_components WHERE dish_id=?', (dish_id,))
        con.executemany(
            'INSERT INTO recipe_components(dish_id,item_id,qty_base,base_unit,sort_order) VALUES(?,?,?,?,?)',
            [(dish_id, *row) for row in normalized],
        )
        if began:
            con.commit()
    except Exception:
        if began and con.in_transaction:
            con.rollback()
        raise

    rows = con.execute(
        'SELECT item_id,qty_base,base_unit,sort_order FROM recipe_components WHERE dish_id=? ORDER BY sort_order,item_id',
        (dish_id,),
    ).fetchall()
    return {'dish_id': dish_id, 'components': [dict(r) for r in rows]}


def recipe_coverage(con: sqlite3.Connection, dish_id: str) -> Coverage:
    ensure_phase3_schema(con)
    rows = con.execute('SELECT item_id FROM recipe_components WHERE dish_id=? ORDER BY sort_order', (str(dish_id),)).fetchall()
    total = len(rows)
    costed = sum(1 for row in rows if _item_unit_cost(con, row['item_id']) is not None)
    ratio = Decimal('0') if total == 0 else Decimal(costed) / Decimal(total)
    return Coverage(total, costed, ratio)


def recipe_cost(con: sqlite3.Connection, dish_id: str) -> RecipeCost:
    ensure_phase3_schema(con)
    dish_id = str(dish_id)
    rows = con.execute('SELECT item_id,qty_base FROM recipe_components WHERE dish_id=? ORDER BY sort_order', (dish_id,)).fetchall()
    known = Decimal('0')
    complete = bool(rows)
    for row in rows:
        unit_cost = _item_unit_cost(con, row['item_id'])
        if unit_cost is None:
            complete = False
            continue
        known += _d(row['qty_base']) * unit_cost

    percent: Decimal | None = None
    if complete and _table_exists(con, 'dishes'):
        dish = con.execute('SELECT price FROM dishes WHERE id=?', (dish_id,)).fetchone()
        if dish and _d(dish['price']) > 0:
            percent = known / _d(dish['price']) * Decimal('100')
    return RecipeCost(dish_id=dish_id, known_cost=known, complete=complete, food_cost_percent=percent)
