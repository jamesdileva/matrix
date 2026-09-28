"""The Void: a deterministic grid world.

The world owns truth. Agents and clients propose; the world validates.

Determinism notes:
- Seeded via ``random.Random(seed)``; string seeds are hashed with sha512
  (CPython), which is stable across runs and platforms.
- Order-sensitive iteration is always row-major or explicitly sorted;
  nothing may depend on set/dict iteration order of unsorted keys.

Nothing in this module imports the database or API layers — the engine is
pure, and persistence lives in outer layers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.simulation.errors import CellOccupiedError, InvalidPositionError

if TYPE_CHECKING:
    from app.simulation.actions import ActionEvent, ActionResult

DEFAULT_OBJECT_TYPES = ("tree", "stone", "food")


class Terrain(str, Enum):
    FLOOR = "floor"
    WALL = "wall"
    WATER = "water"

    @property
    def char(self) -> str:
        return _TERRAIN_CHARS[self]


_TERRAIN_CHARS: dict[Terrain, str] = {
    Terrain.FLOOR: ".",
    Terrain.WALL: "#",
    Terrain.WATER: "~",
}
_CHARS_TO_TERRAIN: dict[str, Terrain] = {c: t for t, c in _TERRAIN_CHARS.items()}

_OBJECT_CHARS = {"tree": "t", "stone": "s", "food": "f"}


@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(x=data["x"], y=data["y"])


@dataclass
class WorldObject:
    id: int
    type: str
    position: Position | None  # None while carried in an entity's inventory
    created_tick: int
    properties: dict = field(default_factory=dict)
    created_by_agent_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "position": self.position.to_dict() if self.position else None,
            "created_tick": self.created_tick,
            "properties": self.properties,
            "created_by_agent_id": self.created_by_agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldObject":
        return cls(
            id=data["id"],
            type=data["type"],
            position=Position.from_dict(data["position"]) if data.get("position") else None,
            created_tick=data["created_tick"],
            properties=data.get("properties") or {},
            created_by_agent_id=data.get("created_by_agent_id"),
        )


class World:
    """A bounded grid world with deterministic seeded generation.

    Rules of ownership:
    - All mutation flows through validated entry points (`place_object`,
      `add_entity`, `execute_action`). There is no other way to change
      state, and invalid proposals never half-apply.
    - Terrain (walls, water) and objects on cells block movement.
    - An entity may share its cell with an object it dropped there, but
      cannot move onto a cell that already holds an object.
    - Every action attempt produces exactly one event.
    """

    def __init__(
        self,
        seed: str | int,
        width: int,
        height: int,
        *,
        tick: int = 0,
        terrain: list[list[Terrain]] | None = None,
        objects: list[WorldObject] | None = None,
        next_object_id: int | None = None,
        entities: dict[int, Position] | None = None,
        inventory: dict[int, list[int]] | None = None,
        events: list[ActionEvent] | None = None,
        next_event_id: int | None = None,
    ):
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError(f"dimensions must be positive integers, got {width}x{height}")
        self.seed = str(seed)
        self.width = width
        self.height = height
        self.tick = tick
        self.terrain = terrain if terrain is not None else [
            [Terrain.FLOOR] * width for _ in range(height)
        ]
        self._objects: dict[int, WorldObject] = {}
        self._occupancy: dict[Position, int] = {}
        for obj in objects or []:
            self._register(obj)
        if next_object_id is not None:
            self._next_object_id = next_object_id
        else:
            self._next_object_id = max(self._objects, default=0) + 1

        self._entities: dict[int, Position] = {}
        self._entity_cells: dict[Position, int] = {}
        for actor_id, position in (entities or {}).items():
            self.add_entity(actor_id, position)

        self._inventory: dict[int, list[int]] = {
            actor_id: list(items) for actor_id, items in (inventory or {}).items()
        }
        self._events: list[ActionEvent] = list(events or [])
        self._next_event_id = (
            next_event_id
            if next_event_id is not None
            else (max((e.id for e in self._events), default=0) + 1)
        )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    @classmethod
    def generate(
        cls,
        seed: str | int,
        width: int = 32,
        height: int = 32,
        *,
        wall_density: float = 0.08,
        water_density: float = 0.06,
        object_density: float = 0.04,
        object_types: tuple[str, ...] = DEFAULT_OBJECT_TYPES,
    ) -> "World":
        """Generate the Void from a seed. Same seed -> identical world."""
        if wall_density < 0 or water_density < 0 or wall_density + water_density > 0.9:
            raise ValueError("terrain densities must be >= 0 and sum to <= 0.9")

        rng = random.Random(seed)
        terrain: list[list[Terrain]] = []
        for y in range(height):
            row: list[Terrain] = []
            for x in range(width):
                if x == 0 or y == 0 or x == width - 1 or y == height - 1:
                    row.append(Terrain.WALL)
                else:
                    r = rng.random()
                    if r < water_density:
                        row.append(Terrain.WATER)
                    elif r < water_density + wall_density:
                        row.append(Terrain.WALL)
                    else:
                        row.append(Terrain.FLOOR)
            terrain.append(row)

        world = cls(seed=seed, width=width, height=height, terrain=terrain)
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                pos = Position(x, y)
                if world.terrain[y][x] is Terrain.FLOOR and rng.random() < object_density:
                    world.place_object(rng.choice(object_types), pos, created_tick=0)
        return world

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def in_bounds(self, position: Position) -> bool:
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def terrain_at(self, position: Position) -> Terrain:
        return self.terrain[position.y][position.x]

    def is_floor(self, position: Position) -> bool:
        return self.in_bounds(position) and self.terrain_at(position) is Terrain.FLOOR

    def object_at(self, position: Position) -> WorldObject | None:
        object_id = self._occupancy.get(position)
        return self._objects.get(object_id) if object_id is not None else None

    def get_object(self, object_id: int) -> WorldObject | None:
        return self._objects.get(object_id)

    @property
    def objects(self) -> list[WorldObject]:
        """All objects, ordered by id (creation order)."""
        return [self._objects[i] for i in sorted(self._objects)]

    # ------------------------------------------------------------------
    # Mutation (validated)
    # ------------------------------------------------------------------

    def step(self) -> int:
        """Advance the simulation tick and apply world dynamics.

        Purely counter-advancing for now; dynamics arrive with resources
        and ecosystem sprints.
        """
        self.tick += 1
        return self.tick

    def place_object(
        self,
        object_type: str,
        position: Position,
        *,
        properties: dict | None = None,
        created_by_agent_id: int | None = None,
        created_tick: int | None = None,
    ) -> WorldObject:
        self._validate_position(position)
        if position in self._occupancy:
            raise CellOccupiedError(f"cell {position.x},{position.y} already holds object {self._occupancy[position]}")

        obj = WorldObject(
            id=self._next_object_id,
            type=object_type,
            position=position,
            created_tick=self.tick if created_tick is None else created_tick,
            properties=properties or {},
            created_by_agent_id=created_by_agent_id,
        )
        self._register(obj)
        self._next_object_id += 1
        return obj

    def _validate_position(self, position: Position) -> None:
        if not isinstance(position.x, int) or not isinstance(position.y, int) or isinstance(position.x, bool) or isinstance(position.y, bool):
            raise InvalidPositionError(f"coordinates must be integers, got {position!r}")
        if not self.in_bounds(position):
            raise InvalidPositionError(
                f"position {position.x},{position.y} is outside a {self.width}x{self.height} world"
            )
        if self.terrain_at(position) is not Terrain.FLOOR:
            raise InvalidPositionError(
                f"position {position.x},{position.y} is on {self.terrain_at(position).value}, objects need floor"
            )

    def _register(self, obj: WorldObject) -> None:
        if obj.id in self._objects:
            raise ValueError(f"duplicate object id {obj.id}")
        if obj.position is None:
            # Carried in some entity's inventory — on the registry, off the grid.
            self._objects[obj.id] = obj
            return
        self._validate_position(obj.position)
        if obj.position in self._occupancy:
            raise CellOccupiedError(f"cell {obj.position.x},{obj.position.y} is occupied")
        self._objects[obj.id] = obj
        self._occupancy[obj.position] = obj.id

    # ------------------------------------------------------------------
    # Entities and inventory
    # ------------------------------------------------------------------

    def add_entity(self, actor_id: int, position: Position) -> None:
        """Register an entity (agent, participant, ...) at a floor cell."""
        if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id <= 0:
            raise ValueError(f"actor id must be a positive integer, got {actor_id!r}")
        if actor_id in self._entities:
            raise ValueError(f"entity {actor_id} already exists")
        self._validate_position(position)
        if position in self._occupancy:
            raise CellOccupiedError(
                f"cell {position.x},{position.y} holds object {self._occupancy[position]}"
            )
        if position in self._entity_cells:
            raise CellOccupiedError(
                f"cell {position.x},{position.y} already holds entity {self._entity_cells[position]}"
            )
        self._entities[actor_id] = position
        self._entity_cells[position] = actor_id

    def remove_entity(self, actor_id: int) -> None:
        """Remove an entity. Refuses while it is still carrying objects."""
        if actor_id not in self._entities:
            raise ValueError(f"unknown entity {actor_id}")
        if self._inventory.get(actor_id):
            raise ValueError(f"entity {actor_id} still carries objects; drop them first")
        position = self._entities.pop(actor_id)
        del self._entity_cells[position]
        self._inventory.pop(actor_id, None)

    def entity_position(self, actor_id: int) -> Position | None:
        return self._entities.get(actor_id)

    @property
    def entity_ids(self) -> list[int]:
        return sorted(self._entities)

    def inventory(self, actor_id: int) -> tuple[int, ...]:
        return tuple(self._inventory.get(actor_id, ()))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def execute_action(self, actor_id, action) -> "ActionResult":
        """The only way entities change the world.

        Accepts an action proposal (a plain dict like
        ``{"action": "move", "direction": "north"}``), validates it against
        the rules, and either applies it or rejects it. Never raises for
        rule violations: rejections come back as an ``ActionResult`` with
        ``ok=False`` plus a recorded event. Exactly one event is recorded
        per attempt, executed or rejected.
        """
        from app.simulation.actions import execute_action

        return execute_action(self, actor_id, action)

    def _record(
        self,
        *,
        ok: bool,
        actor_id,
        action: dict,
        payload: dict,
        data: dict,
    ) -> "ActionResult":
        from app.simulation.actions import ActionEvent, ActionResult

        event = ActionEvent(
            id=self._next_event_id,
            tick=self.tick,
            type="ACTION_EXECUTED" if ok else "ACTION_REJECTED",
            actor_id=actor_id,
            action=action,
            payload=payload,
        )
        self._next_event_id += 1
        self._events.append(event)
        return ActionResult(
            ok=ok, actor_id=actor_id, action=action, event=event, data=data
        )

    @property
    def events(self) -> list["ActionEvent"]:
        """All recorded events, in order. Callers get a copy."""
        return list(self._events)

    # ------------------------------------------------------------------
    # Serialization and display
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "tick": self.tick,
            "next_object_id": self._next_object_id,
            "terrain": ["".join(t.char for t in row) for row in self.terrain],
            "objects": [obj.to_dict() for obj in self.objects],
            "entities": {
                str(actor_id): pos.to_dict()
                for actor_id, pos in sorted(self._entities.items())
            },
            "inventory": {
                str(actor_id): list(items)
                for actor_id, items in sorted(self._inventory.items())
            },
            "next_event_id": self._next_event_id,
            "events": [event.to_dict() for event in self._events],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        from app.simulation.actions import ActionEvent

        try:
            terrain = [
                [_CHARS_TO_TERRAIN[char] for char in row] for row in data["terrain"]
            ]
        except KeyError as exc:
            raise ValueError(f"unknown terrain character in serialized world: {exc}") from exc
        return cls(
            seed=data["seed"],
            width=data["width"],
            height=data["height"],
            tick=data["tick"],
            terrain=terrain,
            objects=[WorldObject.from_dict(o) for o in data["objects"]],
            next_object_id=data["next_object_id"],
            entities={
                int(actor_id): Position.from_dict(pos)
                for actor_id, pos in data.get("entities", {}).items()
            },
            inventory={
                int(actor_id): list(items)
                for actor_id, items in data.get("inventory", {}).items()
            },
            events=[ActionEvent.from_dict(e) for e in data.get("events", [])],
            next_event_id=data.get("next_event_id"),
        )

    def render(self) -> str:
        """ASCII view of the world. Terrain chars, objects overlaid."""
        grid = [[t.char for t in row] for row in self.terrain]
        for obj in self.objects:
            grid[obj.position.y][obj.position.x] = _OBJECT_CHARS.get(obj.type, "?")
        return "\n".join("".join(row) for row in grid)

    def __repr__(self) -> str:
        return (
            f"World(seed={self.seed!r}, {self.width}x{self.height}, "
            f"tick={self.tick}, objects={len(self._objects)})"
        )
