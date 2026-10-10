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

from app.simulation.bus import EventBus
from app.simulation.errors import CellOccupiedError, InvalidPositionError
from app.simulation.events import Event, EventTypes

if TYPE_CHECKING:
    from app.simulation.actions import ActionResult

DEFAULT_OBJECT_TYPES = ("tree", "stone", "food")
# Initial resource quantity per object type (S17). Gathering moves one
# unit per action; a source with none left is depleted and removed.
DEFAULT_OBJECT_QUANTITIES = {"tree": 3, "stone": 3, "food": 2}
# Which resource each object type is a source of (S17).
RESOURCE_OF_OBJECT = {"tree": "wood", "stone": "stone", "food": "food"}
WATER_RESOURCE = "water"

# Building recipes (S18): block type -> material cost from the ledger.
BLOCK_RECIPES = {
    "wood_block": {"wood": 1},
    "stone_block": {"stone": 1},
    "door": {"wood": 1},
}
# How far a voice carries (S21): Manhattan cells, local speech.
SPEECH_RADIUS = 6
# The rolling speech buffer's bound; older utterances are still on the
# timeline (events), just not in anyone's ear.
SPEECH_BUFFER = 50


@dataclass
class Structure:
    """A building: a named collection of placed blocks (guide §13).

    Identity, owner, components, purpose — no architectural realism
    attempted.
    """

    id: int
    owner: int | None
    purpose: str | None
    components: list[int] = field(default_factory=list)  # object ids, placement order


def _resource_kind_of(object_type: str) -> str | None:
    """The resource an object type yields, if any."""
    return RESOURCE_OF_OBJECT.get(object_type)


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
        events: list[Event] | None = None,
        next_event_id: int | None = None,
        event_bus: EventBus | None = None,
        event_retention: int | None = None,
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
            # Restore path: no events emitted while loading a saved world.
            self._add_entity(actor_id, position)

        self._inventory: dict[int, list[int]] = {
            actor_id: list(items) for actor_id, items in (inventory or {}).items()
        }
        # Resource ledger (S17): actor -> resource kind -> amount. The
        # world is the only writer; gathering moves units from object
        # quantities in, spending (S18) moves them out.
        self._resources: dict[int, dict[str, int]] = {}
        # Structures (S18): block object ids grouped by adjacency.
        self._structures: dict[int, Structure] = {}
        self._next_structure_id = 1
        self._structure_of: dict[int, int] = {}  # object id -> structure id
        # Rolling speech buffer (S21): (speaker, position, message, tick).
        self._speeches: list[tuple[int, Position, str, int]] = []
        self._events: list[Event] = list(events or [])
        self._next_event_id = (
            next_event_id
            if next_event_id is not None
            else (max((e.id for e in self._events), default=0) + 1)
        )
        self._event_bus = event_bus
        # Event retention policy (S12): when set, only the most recent N
        # events stay in memory — older ones live in the database (bus
        # subscribers still see everything). Sequence ids keep
        # advancing, so a client's `since_id` window stays coherent
        # within the retained range. Default None: watched live worlds
        # keep every event, because clients stream them.
        self.event_retention = event_retention

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
        event_bus: EventBus | None = None,
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

        world = cls(seed=seed, width=width, height=height, terrain=terrain, event_bus=event_bus)
        world._add_event(
            EventTypes.WORLD_SEEDED,
            payload={
                "width": width,
                "height": height,
                "wall_density": wall_density,
                "water_density": water_density,
                "object_density": object_density,
            },
        )
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                pos = Position(x, y)
                if world.terrain[y][x] is Terrain.FLOOR and rng.random() < object_density:
                    object_type = rng.choice(object_types)
                    world.place_object(
                        object_type,
                        pos,
                        properties={"quantity": DEFAULT_OBJECT_QUANTITIES.get(object_type, 1)},
                        created_tick=0,
                    )
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
        self._add_event(
            EventTypes.OBJECT_CREATED,
            actor_id=created_by_agent_id,
            target_id=obj.id,
            payload={
                "type": object_type,
                "position": position.to_dict(),
                "created_tick": obj.created_tick,
            },
        )
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
        self._add_entity(actor_id, position)
        self._add_event(
            EventTypes.ENTITY_ADDED,
            actor_id=actor_id,
            payload={"position": position.to_dict()},
        )

    def _add_entity(self, actor_id: int, position: Position) -> None:
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
        self._add_event(
            EventTypes.ENTITY_REMOVED,
            actor_id=actor_id,
            payload={"position": position.to_dict()},
        )

    def entity_position(self, actor_id: int) -> Position | None:
        return self._entities.get(actor_id)

    def entity_at(self, position: Position) -> int | None:
        """Which entity stands on a cell, if any."""
        return self._entity_cells.get(position)

    def entity_positions(self) -> dict[int, Position]:
        """All entity positions (a copy; safe to iterate)."""
        return dict(self._entities)

    @property
    def entity_ids(self) -> list[int]:
        return sorted(self._entities)

    def inventory(self, actor_id: int) -> tuple[int, ...]:
        return tuple(self._inventory.get(actor_id, ()))

    # ------------------------------------------------------------------
    # Resources (S17)
    # ------------------------------------------------------------------

    def resource_count(self, actor_id: int, kind: str) -> int:
        """How much of one resource an entity carries."""
        return self._resources.get(actor_id, {}).get(kind, 0)

    # ------------------------------------------------------------------
    # Speech (S21)
    # ------------------------------------------------------------------

    def say(self, actor_id: int, message: str) -> Event:
        """An entity speaks aloud; the utterance lands on the timeline.

        The speaker must be in the world. Hearing is local: only
        entities within ``SPEECH_RADIUS`` see the message in their next
        observation (``messages_for``), and the rolling buffer is the
        ear's memory — the events table remains the full record.
        """
        position = self._entities.get(actor_id)
        if position is None:
            raise ValueError(f"unknown speaker {actor_id!r}")
        event = self._add_event(
            EventTypes.SPEECH,
            actor_id=actor_id,
            payload={"message": message, "position": position.to_dict()},
        )
        self._speeches.append((actor_id, position, message, self.tick))
        if len(self._speeches) > SPEECH_BUFFER:
            del self._speeches[: len(self._speeches) - SPEECH_BUFFER]
        return event

    def messages_for(self, actor_id: int) -> list[dict]:
        """What `actor_id` can hear: recent speech within the radius."""
        position = self._entities.get(actor_id)
        if position is None:
            return []
        heard = []
        for speaker, spoke_at, message, tick in self._speeches:
            if speaker == actor_id:
                continue  # you do not hear yourself
            if abs(position.x - spoke_at.x) + abs(position.y - spoke_at.y) <= SPEECH_RADIUS:
                heard.append(
                    {"from": speaker, "message": message, "tick": tick,
                     "distance": abs(position.x - spoke_at.x) + abs(position.y - spoke_at.y)}
                )
        return heard

    def resources(self, actor_id: int) -> dict:
        """An entity's whole ledger (a copy)."""
        return dict(self._resources.get(actor_id, {}))

    def credit_resource(self, actor_id: int, kind: str, amount: int) -> None:
        """Add resources to an entity's ledger (gathering lands here)."""
        if amount < 0:
            raise ValueError(f"credit must be positive, got {amount}")
        ledger = self._resources.setdefault(actor_id, {})
        ledger[kind] = ledger.get(kind, 0) + amount

    def spend_resource(self, actor_id: int, kind: str, amount: int) -> bool:
        """Remove resources if the ledger covers them; False otherwise."""
        ledger = self._resources.get(actor_id, {})
        if ledger.get(kind, 0) < amount:
            return False
        ledger[kind] -= amount
        if ledger[kind] == 0:
            del ledger[kind]
        return True

    def total_resources(self) -> dict:
        """Every resource unit in the world: object quantities + ledgers.

        The conservation invariant's witness — gathering moves units
        between these two pools and creates nothing.
        """
        totals: dict[str, int] = {}
        for obj in self._objects.values():
            if obj.position is None:  # carried: not a world-side source
                continue
            kind = _resource_kind_of(obj.type)
            if kind is not None:
                totals[kind] = totals.get(kind, 0) + obj.properties.get("quantity", 0)
        for ledger in self._resources.values():
            for kind, amount in ledger.items():
                totals[kind] = totals.get(kind, 0) + amount
        return totals

    def remove_object(self, object_id: int) -> None:
        """Take a depleted source out of the world, with its event."""
        obj = self._objects.get(object_id)
        if obj is None:
            raise ValueError(f"unknown object {object_id!r}")
        position = obj.position
        del self._objects[object_id]
        if position is not None:
            self._occupancy.pop(position, None)
        self._add_event(
            EventTypes.OBJECT_DEPLETED,
            target_id=object_id,
            payload={"type": obj.type, "position": position.to_dict() if position else None},
        )

    # ------------------------------------------------------------------
    # Structures (S18)
    # ------------------------------------------------------------------

    def structures(self) -> list[Structure]:
        """All structures, in creation order."""
        return [self._structures[i] for i in sorted(self._structures)]

    def structure_by_id(self, structure_id: int) -> Structure | None:
        """One structure, or None."""
        return self._structures.get(structure_id)

    def structure_of(self, object_id: int) -> int | None:
        """Which structure a block belongs to, if any."""
        return self._structure_of.get(object_id)

    def structure_for_cell(self, position: Position) -> int | None:
        """The structure a new block at `position` would join.

        When several adjacent structures meet at the new block, they
        merge into the oldest — two walls that touch are one building,
        whichever order they were raised in.
        """
        found = set()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = Position(position.x + dx, position.y + dy)
            object_id = self._occupancy.get(cell)
            structure_id = self._structure_of.get(object_id) if object_id else None
            if structure_id is not None:
                found.add(structure_id)
        if not found:
            return None
        target = min(found)
        for other in found - {target}:  # merge the rest into the oldest
            self._merge_structures(target, other)
        return target

    def _merge_structures(self, target_id: int, source_id: int) -> None:
        """Fold one structure into another."""
        source = self._structures.pop(source_id, None)
        if source is None:  # pragma: no cover - set and rows agree
            return
        target = self._structures[target_id]
        for object_id in source.components:
            self._structure_of[object_id] = target_id
        target.components.extend(source.components)
        if target.purpose is None:
            target.purpose = source.purpose

    def create_structure(self, *, owner: int | None, purpose: str | None) -> int:
        """Start a new structure; emits STRUCTURE_CREATED."""
        structure_id = self._next_structure_id
        self._next_structure_id += 1
        self._structures[structure_id] = Structure(
            id=structure_id, owner=owner, purpose=purpose
        )
        self._add_event(
            EventTypes.STRUCTURE_CREATED,
            actor_id=owner,
            target_id=structure_id,
            payload={"owner": owner, "purpose": purpose},
        )
        return structure_id

    def add_to_structure(self, structure_id: int, object_id: int) -> None:
        """Attach a placed block to a structure."""
        if structure_id not in self._structures:
            raise ValueError(f"unknown structure {structure_id!r}")
        self._structure_of[object_id] = structure_id
        self._structures[structure_id].components.append(object_id)

    def remove_block(self, object_id: int) -> None:
        """Take a placed block out of the world and its structure."""
        self.remove_object(object_id)
        structure_id = self._structure_of.pop(object_id, None)
        if structure_id is None:
            return
        structure = self._structures.get(structure_id)
        if structure is None:  # pragma: no cover - map and rows agree
            return
        if object_id in structure.components:
            structure.components.remove(object_id)
        if not structure.components:
            del self._structures[structure_id]  # an empty structure is gone

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

    def _record_action(self, *, ok: bool, actor_id, action: dict, data: dict) -> "ActionResult":
        from app.simulation.actions import ActionResult

        event = self._add_event(
            EventTypes.ACTION_EXECUTED if ok else EventTypes.ACTION_REJECTED,
            actor_id=actor_id,
            payload={"action": action, **data},
        )
        return ActionResult(
            ok=ok, actor_id=actor_id, action=action, event=event, data=data
        )

    def _add_event(
        self,
        event_type: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        payload: dict | None = None,
    ) -> Event:
        """Record an event, advance the sequence, and publish to the bus."""
        event = Event(
            id=self._next_event_id,
            tick=self.tick,
            type=event_type,
            actor_id=actor_id,
            target_id=target_id,
            payload=payload or {},
        )
        self._next_event_id += 1
        self._events.append(event)
        if self.event_retention is not None and len(self._events) > self.event_retention:
            del self._events[: len(self._events) - self.event_retention]
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event

    @property
    def events(self) -> list[Event]:
        """All recorded events, in order. Callers get a copy."""
        return list(self._events)

    # ------------------------------------------------------------------
    # Serialization and display
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Client-facing state: everything needed to render the world,
        nothing else (no events, no bookkeeping ids)."""
        return {
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "tick": self.tick,
            "terrain": ["".join(t.char for t in row) for row in self.terrain],
            "objects": [
                {"id": obj.id, "type": obj.type, "quantity": obj.properties.get("quantity"),
                 "position": obj.position.to_dict()}
                for obj in self.objects
                if obj.position is not None
            ],
            "entities": {
                str(actor_id): pos.to_dict()
                for actor_id, pos in sorted(self._entities.items())
            },
        }

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
            events=[Event.from_dict(e) for e in data.get("events", [])],
            next_event_id=data.get("next_event_id"),
        )

    def render(self) -> str:
        """ASCII view of the world. Terrain chars, then objects, then
        entities (``@``) on top."""
        grid = [[t.char for t in row] for row in self.terrain]
        for obj in self.objects:
            grid[obj.position.y][obj.position.x] = _OBJECT_CHARS.get(obj.type, "?")
        for position in self._entity_cells:
            grid[position.y][position.x] = "@"
        return "\n".join("".join(row) for row in grid)

    def __repr__(self) -> str:
        return (
            f"World(seed={self.seed!r}, {self.width}x{self.height}, "
            f"tick={self.tick}, objects={len(self._objects)})"
        )
