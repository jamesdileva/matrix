"""Action proposals: the only way entities change the world.

An action is a plain dict, e.g. ``{"action": "move", "direction": "north"}``.
The dispatcher validates it against the world's rules and either applies it
or rejects it with a reason. A rejected action never mutates world state;
every attempt, valid or not, records exactly one event.

This module is part of the engine package and deliberately touches World
internals — the two evolve together. Nothing outside the package may do
the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.simulation.events import Event
from app.simulation.world import RESOURCE_OF_OBJECT, WATER_RESOURCE, Position, Terrain, World

RESOURCE_SOURCES = {
    resource: object_type for object_type, resource in RESOURCE_OF_OBJECT.items()
}  # resource kind -> object type that yields it
GATHER_YIELD = 1  # units per gather action (scarcity is the point)

DIRECTIONS: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    actor_id: int | None
    action: dict
    event: Event
    data: dict = field(default_factory=dict)

    @property
    def reason(self) -> str | None:
        return self.data.get("reason")


class _Rejected(Exception):
    """Internal control flow: a rule violation carrying a reason."""

    def __init__(self, reason: str, data: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.data = data or {}


HANDLERS = {
    "move": "_move",
    "look": "_look",
    "inspect": "_inspect",
    "pick_up": "_pick_up",
    "drop": "_drop",
    "place": "_place",
    "gather": "_gather",
}


def execute_action(world: World, actor_id, action) -> ActionResult:
    """Validate and apply one action proposal."""
    if not isinstance(action, dict):
        return world._record_action(
            ok=False, actor_id=actor_id, action={}, data={"reason": "invalid_action"}
        )

    handler_name = HANDLERS.get(action.get("action"))
    if handler_name is None:
        return world._record_action(
            ok=False,
            actor_id=actor_id,
            action=action,
            data={"reason": "unknown_action"},
        )

    handler = globals()[handler_name]
    try:
        data = handler(world, actor_id, action)
    except _Rejected as exc:
        return world._record_action(
            ok=False,
            actor_id=actor_id,
            action=action,
            data={"reason": exc.reason, **exc.data},
        )
    return world._record_action(ok=True, actor_id=actor_id, action=action, data=data)


def _gather(world: World, actor_id, action: dict) -> dict:
    """Move one unit of a resource from an adjacent source into the
    actor's ledger (S17).

    Sources: the object type that yields the resource (a tree for
    wood), or an adjacent water tile for water. A source that hits
    zero is depleted and leaves the world. Rejections record like any
    other rule violation; nothing is half-applied.
    """
    position = _require_actor(world, actor_id)
    resource = action.get("resource")
    if not isinstance(resource, str) or (
        resource not in RESOURCE_SOURCES and resource != WATER_RESOURCE
    ):
        raise _Rejected("unknown_resource", {"resource": resource})

    if resource == WATER_RESOURCE:
        if not any(
            world.in_bounds(Position(position.x + dx, position.y + dy))
            and world.terrain_at(Position(position.x + dx, position.y + dy)) is Terrain.WATER
            for dx, dy in DIRECTIONS.values()
        ):
            raise _Rejected("no_water_nearby", {"resource": resource})
        world.credit_resource(actor_id, resource, GATHER_YIELD)
        return {"resource": resource, "amount": GATHER_YIELD}

    source_type = RESOURCE_SOURCES[resource]
    for dx, dy in DIRECTIONS.values():
        cell = Position(position.x + dx, position.y + dy)
        if not world.in_bounds(cell):
            continue
        obj = world.object_at(cell)
        if obj is None or obj.type != source_type:
            continue
        quantity = obj.properties.get("quantity", 0)
        if not isinstance(quantity, int) or quantity <= 0:
            continue
        obj.properties["quantity"] = quantity - GATHER_YIELD
        world.credit_resource(actor_id, resource, GATHER_YIELD)
        depleted = False
        if obj.properties["quantity"] <= 0:
            world.remove_object(obj.id)
            depleted = True
        return {
            "resource": resource,
            "amount": GATHER_YIELD,
            "source_object_id": obj.id,
            "depleted": depleted,
        }
    raise _Rejected("no_source_nearby", {"resource": resource, "wanted": source_type})


# ----------------------------------------------------------------------
# Shared validation
# ----------------------------------------------------------------------


def _require_actor(world: World, actor_id):
    if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id not in world._entities:
        raise _Rejected("unknown_actor", {"actor_id": actor_id})
    return world._entities[actor_id]


def _carried(world: World, actor_id: int, object_id):
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.id not in world._inventory.get(actor_id, []):
        raise _Rejected("not_carrying", {"object_id": object_id})
    return obj


def _within_reach(actor_position, object_position) -> bool:
    if object_position is None:
        return False
    return abs(actor_position.x - object_position.x) + abs(actor_position.y - object_position.y) <= 1


# ----------------------------------------------------------------------
# Handlers — return data on success, raise _Rejected on rule violations
# ----------------------------------------------------------------------


def _move(world: World, actor_id, action: dict) -> dict:
    from app.simulation.world import Position, Terrain

    position = _require_actor(world, actor_id)
    direction = action.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise _Rejected("invalid_direction", {"direction": direction})

    dx, dy = DIRECTIONS[direction]
    target = Position(position.x + dx, position.y + dy)
    if not world.in_bounds(target):
        raise _Rejected("out_of_bounds", {"to": target.to_dict()})
    terrain = world.terrain_at(target)
    if terrain is Terrain.WALL:
        raise _Rejected("wall", {"to": target.to_dict()})
    if terrain is Terrain.WATER:
        raise _Rejected("water", {"to": target.to_dict()})
    if target in world._occupancy:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "object_id": world._occupancy[target]}
        )
    if target in world._entity_cells:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "entity_id": world._entity_cells[target]}
        )

    del world._entity_cells[position]
    world._entities[actor_id] = target
    world._entity_cells[target] = actor_id
    return {"from": position.to_dict(), "to": target.to_dict()}


def _look(world: World, actor_id, action: dict) -> dict:
    from app.simulation.world import Position

    position = _require_actor(world, actor_id)
    cells = []
    for name, (dx, dy) in [("here", (0, 0))] + list(DIRECTIONS.items()):
        cell_pos = Position(position.x + dx, position.y + dy)
        cell: dict = {"direction": name, "position": cell_pos.to_dict()}
        if not world.in_bounds(cell_pos):
            cell["terrain"] = "void"
        else:
            cell["terrain"] = world.terrain_at(cell_pos).value
            obj = world.object_at(cell_pos)
            if obj is not None:
                cell["object"] = {"id": obj.id, "type": obj.type}
            entity = world._entity_cells.get(cell_pos)
            if entity is not None:
                cell["entity"] = entity
        cells.append(cell)
    return {"position": position.to_dict(), "cells": cells}


def _inspect(world: World, actor_id, action: dict) -> dict:
    position = _require_actor(world, actor_id)
    object_id = action.get("object_id")
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.position is None:
        # Carried: only the carrier can inspect it up close.
        if obj.id not in world._inventory.get(actor_id, []):
            raise _Rejected("carried_elsewhere", {"object_id": obj.id})
    elif not _within_reach(position, obj.position):
        raise _Rejected("out_of_reach", {"object_position": obj.position.to_dict()})
    return {"object": obj.to_dict()}


def _pick_up(world: World, actor_id, action: dict) -> dict:
    position = _require_actor(world, actor_id)
    object_id = action.get("object_id")
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.position is None:
        raise _Rejected("carried_elsewhere", {"object_id": obj.id})
    if not _within_reach(position, obj.position):
        raise _Rejected("out_of_reach", {"object_position": obj.position.to_dict()})

    del world._occupancy[obj.position]
    obj.position = None
    world._inventory.setdefault(actor_id, []).append(obj.id)
    return {"object_id": obj.id, "type": obj.type, "from": None}


def _drop(world: World, actor_id, action: dict) -> dict:
    return _release(world, actor_id, action, allow_direction=False)


def _place(world: World, actor_id, action: dict) -> dict:
    return _release(world, actor_id, action, allow_direction=True)


def _release(world: World, actor_id, action: dict, *, allow_direction: bool) -> dict:
    from app.simulation.world import Position, Terrain

    verb = "place" if allow_direction else "drop"
    position = _require_actor(world, actor_id)
    obj = _carried(world, actor_id, action.get("object_id"))

    if allow_direction:
        direction = action.get("direction")
        if not isinstance(direction, str) or direction not in DIRECTIONS:
            raise _Rejected("invalid_direction", {"direction": direction})
        dx, dy = DIRECTIONS[direction]
        target = Position(position.x + dx, position.y + dy)
    else:
        target = position

    if not world.in_bounds(target):
        raise _Rejected("out_of_bounds", {"to": target.to_dict()})
    if world.terrain_at(target) is not Terrain.FLOOR:
        raise _Rejected("impassable_terrain", {"to": target.to_dict()})
    if target in world._occupancy:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "object_id": world._occupancy[target]}
        )
    if allow_direction and target in world._entity_cells:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "entity_id": world._entity_cells[target]}
        )

    world._inventory[actor_id].remove(obj.id)
    if not world._inventory[actor_id]:
        del world._inventory[actor_id]
    obj.position = target
    world._occupancy[target] = obj.id
    return {"object_id": obj.id, "type": obj.type, "to": target.to_dict(), "verb": verb}
