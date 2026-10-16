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
from app.simulation.budget import AGENT_KINDS, Budget, KINDS, LimitExceeded
from app.simulation.games import GameSession, validate_rules
from app.simulation.geometry import Position
from app.simulation.technology import (
    BASE_RECIPES,
    TOOLS,
    Pattern,
    Recipe,
    knowledge_item,
)
from app.simulation.settlement import (
    PURPOSE_HOME,
    PURPOSE_STORAGE,
    SETTLEMENT_EXTENT,
    Road,
    Settlement,
)

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
# Now derived from the world's public recipe knowledge (S29) — the
# data in `technology` is the source; this is the builders' view of it.
BLOCK_RECIPES = {
    name: dict(recipe.inputs)
    for name, recipe in BASE_RECIPES.items()
    if name in ("wood_block", "stone_block", "door")
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


def _clean_budget_value(kind: str, value):
    """One budget cap, validated where it is set."""
    from app.simulation.budget import _clean

    return _clean(value, kind)



def _budget_from_ledger(ledger: dict) -> "Budget":
    """A ledger's full report (spent/cap/remaining) back into a Budget."""
    from app.simulation.budget import KINDS, Budget

    budget = Budget.from_dict(
        {kind: (ledger.get(kind) or {}).get("cap") for kind in KINDS}
    )
    for kind in KINDS:
        budget.spent[kind] = (ledger.get(kind) or {}).get("spent", 0)
    return budget

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
        # Routed letters (S28): named, group and global messages, as
        # dicts — {sender, kind, address, message, tick, recipients}.
        # The recipients are frozen at send time; leaving the world
        # later does not un-deliver. Bounded like the speech buffer.
        self._letters: list[dict] = []
        # Population membership (S28): entity -> population id. The
        # engine writes it at spawn; the manager reads it to route.
        self._entity_populations: dict[int, int] = {}
        # Follow directives (S22): follower -> target entity id.
        self._following: dict[int, int] = {}
        # Technology (S29): the recipes and patterns the world has
        # ever known (seeded with the public ones), and per-entity
        # *known* sets — what an agent can craft or build. Discoveries
        # and inventions add to both; inheritance grants a child its
        # parent's known technology.
        self._recipes: dict[str, Recipe] = dict(BASE_RECIPES)
        self._patterns: dict[str, Pattern] = {}
        self._known_recipes: dict[int, set[str]] = {}
        self._known_patterns: dict[int, set[str]] = {}
        # Settlements (S30): the communities, their roads, and the
        # resource zones they hold (object id -> settlement id).
        self._settlements: dict[int, Settlement] = {}
        self._roads: dict[int, Road] = {}
        self._zones: dict[int, int] = {}
        self._next_settlement_id = 1
        self._next_road_id = 1
        # Games (S31): proposed rules and the tables playing them.
        self._games: dict[int, dict] = {}
        self._sessions: dict[int, GameSession] = {}
        self._next_game_id = 1
        self._next_session_id = 1
        # Compute budgets (S33): what every entity and the experiment
        # itself may spend. Absent kinds are unlimited — the constraint
        # is opt-in.
        self._budgets: dict[int, Budget] = {}
        self._experiment_budget: Budget | None = None
        # Teams (S25): team id -> member entity ids. Shared
        # observations list teammates by team, not by population.
        self._teams: dict[int, set[int]] = {}
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
        self._entity_populations.pop(actor_id, None)
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
        """What `actor_id` can hear: recent speech within the radius,
        plus every routed letter addressed to them (S28).

        Local entries carry a distance; routed ones carry their kind
        and address instead — a mind can tell a whisper from a
        broadcast by looking.
        """
        position = self._entities.get(actor_id)
        if position is None:
            return []
        heard = []
        for speaker, spoke_at, message, tick in self._speeches:
            if speaker == actor_id:
                continue  # you do not hear yourself
            if abs(position.x - spoke_at.x) + abs(position.y - spoke_at.y) <= SPEECH_RADIUS:
                heard.append(
                    {"from": speaker, "message": message, "tick": tick, "kind": "say",
                     "distance": abs(position.x - spoke_at.x) + abs(position.y - spoke_at.y)}
                )
        for letter in self._letters:
            if letter["sender"] == actor_id or actor_id not in letter["recipients"]:
                continue
            entry = {
                "from": letter["sender"],
                "message": letter["message"],
                "tick": letter["tick"],
                "kind": letter["kind"],
                "distance": None,
            }
            if letter["kind"] == "tell":
                entry["to"] = letter["address"]
            elif letter["kind"] == "announce":
                entry["scope"] = letter["address"]
            heard.append(entry)
        return heard

    # ------------------------------------------------------------------
    # Communication networks (S28)
    # ------------------------------------------------------------------

    def team_of(self, entity_id: int) -> int | None:
        """The team an entity stands on, if any."""
        for team_id, members in self._teams.items():
            if entity_id in members:
                return team_id
        return None

    def set_population(self, entity_id: int, population_id: int | None) -> None:
        """Record an entity's population (the engine writes it at spawn)."""
        if population_id is None:
            self._entity_populations.pop(entity_id, None)
        else:
            self._entity_populations[entity_id] = population_id

    def population_of(self, entity_id: int) -> int | None:
        """The population an entity belongs to, if any."""
        return self._entity_populations.get(entity_id)

    def route_message(self, sender_id: int, kind: str, address) -> list[int]:
        """Who receives a message: the routing, as a decision.

        - ``tell`` to a target: that one entity, wherever it stands.
        - ``announce`` to ``team``/``population``: the sender's group.
        - ``broadcast``: every entity in the world.
        The sender never receives their own message. Recipients must
        be in the world; membership is read now, delivery frozen.
        """
        if sender_id not in self._entities:
            raise ValueError(f"unknown sender {sender_id!r}")
        if kind == "tell":
            if address not in self._entities:
                raise ValueError(f"unknown recipient {address!r}")
            recipients = [address]
        elif kind == "announce" and address == "team":
            team_id = self.team_of(sender_id)
            if team_id is None:
                raise ValueError(f"entity {sender_id} stands on no team")
            recipients = sorted(self._teams[team_id])
        elif kind == "announce" and address == "population":
            population_id = self.population_of(sender_id)
            if population_id is None:
                raise ValueError(f"entity {sender_id} belongs to no population")
            recipients = sorted(
                entity_id
                for entity_id, member_of in self._entity_populations.items()
                if member_of == population_id and entity_id in self._entities
            )
        elif kind == "broadcast":
            recipients = sorted(self._entities)
        else:
            raise ValueError(f"cannot route kind={kind!r} address={address!r}")
        return [entity_id for entity_id in recipients if entity_id != sender_id]

    def _buffer_letter(self, sender_id: int, kind: str, address, message: str) -> list[int]:
        recipients = self.route_message(sender_id, kind, address)
        self._letters.append(
            {
                "sender": sender_id,
                "kind": kind,
                "address": address,
                "message": message,
                "tick": self.tick,
                "recipients": recipients,
            }
        )
        if len(self._letters) > SPEECH_BUFFER:
            del self._letters[: len(self._letters) - SPEECH_BUFFER]
        return recipients

    def tell(self, sender_id: int, target_id: int, message: str) -> Event:
        """A named letter: one recipient, whatever the distance.

        The hallway conversation made reliable — a `tell` is delivered
        into the recipient's inbox even across the map, and recorded as
        a DIRECT event naming both parties.
        """
        recipients = self._buffer_letter(sender_id, "tell", target_id, message)
        return self._add_event(
            EventTypes.DIRECT,
            actor_id=sender_id,
            target_id=target_id,
            payload={"message": message, "recipients": recipients},
        )

    def announce(self, sender_id: int, scope: str, message: str) -> Event:
        """One message to the sender's whole group: team or population.

        The crier's solution to the chain's problem — instead of
        telling members one by one, the group hears it at once. The
        ANNOUNCE event names the scope and the recipients.
        """
        recipients = self._buffer_letter(sender_id, "announce", scope, message)
        return self._add_event(
            EventTypes.ANNOUNCE,
            actor_id=sender_id,
            payload={"message": message, "scope": scope, "recipients": recipients},
        )

    def broadcast(self, sender_id: int, message: str) -> Event:
        """One message to every entity in the world.

        Distance stops mattering entirely — the town square's loudest
        voice. Recorded as a BROADCAST event naming the recipients.
        """
        recipients = self._buffer_letter(sender_id, "broadcast", "all", message)
        return self._add_event(
            EventTypes.BROADCAST,
            actor_id=sender_id,
            payload={"message": message, "recipients": recipients},
        )

    # ------------------------------------------------------------------
    # Technology (S29)
    # ------------------------------------------------------------------

    # --- registries: what the world knows ---

    @property
    def recipes(self) -> dict[str, Recipe]:
        """Every recipe the world has ever known (a copy)."""
        return dict(self._recipes)

    @property
    def patterns(self) -> dict[str, Pattern]:
        """Every construction pattern the world has ever known (a copy)."""
        return dict(self._patterns)

    def add_recipe(self, recipe: Recipe) -> None:
        """Teach the world a recipe (an invention, once)."""
        self._recipes[recipe.name] = recipe

    def add_pattern(self, pattern: Pattern) -> None:
        """Teach the world a construction pattern."""
        self._patterns[pattern.name] = pattern

    # --- per-entity knowledge: what an agent can do ---

    def known_recipes(self, actor_id: int) -> list[str]:
        return sorted(self._known_recipes.get(actor_id, ()))

    def known_patterns(self, actor_id: int) -> list[str]:
        return sorted(self._known_patterns.get(actor_id, ()))

    def technology_of(self, actor_id: int) -> list[str]:
        """The agent's technology knowledge, as knowledge strings."""
        return [knowledge_item(self._recipes[name]) for name in self.known_recipes(actor_id)] + [
            knowledge_item(self._patterns[name]) for name in self.known_patterns(actor_id)
        ]

    def grant_knowledge(self, actor_id: int, knowledge: list) -> list[str]:
        """Grant knowledge to an entity; returns the technology granted.

        Plain facts (S10's knowledge) pass through untouched — they
        travel with the agent's own list. ``recipe:``/``pattern:``
        strings are parsed into the entity's known sets, so an inherited
        recipe is usable the moment its carrier exists. Strings naming
        technology the world does not know are simply not usable: a
        birth must never fail over a typo.
        """
        granted: list[str] = []
        for item in knowledge or []:
            if not isinstance(item, str):
                continue
            if item.startswith("recipe:"):
                name = item[len("recipe:"):]
                if name in self._recipes:
                    self._known_recipes.setdefault(actor_id, set()).add(name)
                    granted.append(item)
            elif item.startswith("pattern:"):
                name = item[len("pattern:"):]
                if name in self._patterns:
                    self._known_patterns.setdefault(actor_id, set()).add(name)
                    granted.append(item)
        return granted

    def discoverable(self, actor_id: int) -> list[Recipe]:
        """Recipes the world knows that this entity does not, and could
        experiment its way to from what it already carries (S29)."""
        ledger = self.resources(actor_id)
        known = self._known_recipes.get(actor_id, set())
        return sorted(
            (
                recipe
                for name, recipe in self._recipes.items()
                if name not in known and recipe.affordable_by(ledger)
            ),
            key=lambda recipe: recipe.name,
        )

    def carried_objects(self, actor_id: int) -> list[dict]:
        """What the entity carries, as objects (not just ids)."""
        return [
            {
                "id": object_id,
                "type": self._objects[object_id].type,
                "properties": dict(self._objects[object_id].properties),
            }
            for object_id in self.inventory(actor_id)
            if object_id in self._objects
        ]

    def tool_effect(self, actor_id: int, effect: str) -> int:
        """The multiplier a carried tool grants, e.g. ``gather`` (S29)."""
        multiplier = 1
        for object_id in self.inventory(actor_id):
            obj = self._objects.get(object_id)
            if obj is None:
                continue
            tool = TOOLS.get(obj.type)
            if tool and effect in tool:
                multiplier *= tool[effect]
        return multiplier

    def carve_object(self, object_type: str, actor_id: int, properties: dict | None = None) -> "WorldObject":
        """Make an object straight into an entity's hands (S29).

        Crafting is not placing: the thing comes to be *carried*, on
        the registry but off the grid. It emits an OBJECT_CREATED
        event like anything else the world gains.
        """
        obj = WorldObject(
            id=self._next_object_id,
            type=object_type,
            position=None,  # carried, not placed
            created_tick=self.tick,
            properties=properties or {},
            created_by_agent_id=actor_id,
        )
        self._register(obj)
        self._next_object_id += 1
        self._inventory.setdefault(actor_id, []).append(obj.id)
        self._add_event(
            EventTypes.OBJECT_CREATED,
            actor_id=actor_id,
            target_id=obj.id,
            payload={
                "type": object_type,
                "position": None,
                "carried": True,
                "created_tick": obj.created_tick,
            },
        )
        return obj

    # ------------------------------------------------------------------
    # Social interaction (S22)
    # ------------------------------------------------------------------

    def carried_by(self, object_id: int) -> int | None:
        """Which entity carries an object, if any."""
        for actor_id, items in self._inventory.items():
            if object_id in items:
                return actor_id
        return None

    def transfer_object(self, object_id: int, to_id: int) -> None:
        """Move a carried object into another entity's inventory.

        Requires the object to be carried by someone (not on the grid)
        and the recipient to be in the world.
        """
        if to_id not in self._entities:
            raise ValueError(f"unknown recipient {to_id!r}")
        holder = self.carried_by(object_id)
        if holder is None:
            raise ValueError(f"object {object_id} is not carried by anyone")
        self._inventory[holder].remove(object_id)
        if not self._inventory[holder]:
            del self._inventory[holder]
        self._inventory.setdefault(to_id, []).append(object_id)

    def set_follow(self, follower_id: int, target_id: int) -> None:
        """`follower_id` starts walking with `target_id`."""
        if target_id not in self._entities:
            raise ValueError(f"unknown follow target {target_id!r}")
        if follower_id not in self._entities:
            raise ValueError(f"unknown follower {follower_id!r}")
        self._following[follower_id] = target_id

    def clear_follow(self, follower_id: int) -> bool:
        """Stop following; False if there was nothing to stop."""
        return self._following.pop(follower_id, None) is not None

    def follow_target(self, follower_id: int) -> int | None:
        """Who this entity follows, if anyone (and they still exist)."""
        target = self._following.get(follower_id)
        if target is not None and target not in self._entities:
            self._following.pop(follower_id, None)
            return None
        return target

    def add_to_team(self, entity_id: int, team_id: int) -> None:
        """Put an entity on a team (S25)."""
        if entity_id not in self._entities:
            raise ValueError(f"unknown entity {entity_id!r}")
        self._teams.setdefault(team_id, set()).add(entity_id)

    def teammates_of(self, entity_id: int) -> list[dict]:
        """The entity's teammates (same team), as id + position."""
        for members in self._teams.values():
            if entity_id in members:
                return [
                    {"id": member, "position": self._entities[member].to_dict()}
                    for member in sorted(members)
                    if member != entity_id and member in self._entities
                ]
        return []

    def step_toward(self, follower_id: int, target_id: int) -> "ActionResult":
        """One validated step from the follower toward the target."""
        from app.simulation.actions import execute_action

        here = self._entities.get(follower_id)
        there = self._entities.get(target_id)
        if here is None or there is None:
            raise ValueError(f"unknown entities in follow step: {follower_id} -> {target_id}")
        dx = there.x - here.x
        dy = there.y - here.y
        for direction in ("east", "west") if abs(dx) >= abs(dy) else ("south", "north"):
            if (direction == "east" and dx > 0) or (direction == "west" and dx < 0) or (
                direction == "south" and dy > 0
            ) or (direction == "north" and dy < 0):
                return execute_action(
                    self, follower_id, {"action": "move", "direction": direction}
                )
        # Adjacent (or overlapping): nothing to do this tick.
        from app.simulation.actions import ActionResult

        return ActionResult(
            ok=True,
            actor_id=follower_id,
            action={"action": "look"},
            event=self._add_event(
                EventTypes.ACTION_EXECUTED,
                actor_id=follower_id,
                payload={"action": {"action": "look"}, "reason": "following"},
            ),
            data={"following": target_id},
        )

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
            # What a civilization *is*, beyond the grid (S38): the
            # derived systems a snapshot must carry or a resumed world
            # would be a field with amnesia.
            "resources": {
                str(actor_id): dict(ledger)
                for actor_id, ledger in sorted(self._resources.items())
            },
            "structures": [
                {
                    "id": structure.id,
                    "owner": structure.owner,
                    "purpose": structure.purpose,
                    "components": list(structure.components),
                }
                for structure in self.structures()
            ],
            "structure_of": {
                str(object_id): structure_id
                for object_id, structure_id in sorted(self._structure_of.items())
            },
            "settlements": [settlement.to_dict() for settlement in self.settlements],
            "roads": [road.to_dict() for road in self.roads],
            "zones": {str(object_id): settlement_id for object_id, settlement_id in self._zones.items()},
            "games": [dict(game) for game in self.games],
            "sessions": [session.to_dict() for session in self.sessions],
            "recipes": [recipe.to_dict() for recipe in self._recipes.values()],
            "patterns": [pattern.to_dict() for pattern in self._patterns.values()],
            "known_recipes": {
                str(entity_id): sorted(names)
                for entity_id, names in sorted(self._known_recipes.items())
            },
            "known_patterns": {
                str(entity_id): sorted(names)
                for entity_id, names in sorted(self._known_patterns.items())
            },
            "teams": {
                str(team_id): sorted(members) for team_id, members in sorted(self._teams.items())
            },
            "following": {
                str(follower): target for follower, target in sorted(self._following.items())
            },
            "populations": {
                str(entity_id): population_id
                for entity_id, population_id in sorted(self._entity_populations.items())
            },
            "budgets": {
                str(entity_id): budget.to_dict()
                for entity_id, budget in sorted(self._budgets.items())
            },
            "experiment_budget": (
                self._experiment_budget.to_dict() if self._experiment_budget else None
            ),
            "speeches": [
                {
                    "speaker": speaker,
                    "position": spoke_at.to_dict(),
                    "message": message,
                    "tick": tick,
                }
                for speaker, spoke_at, message, tick in self._speeches
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        try:
            terrain = [
                [_CHARS_TO_TERRAIN[char] for char in row] for row in data["terrain"]
            ]
        except KeyError as exc:
            raise ValueError(f"unknown terrain character in serialized world: {exc}") from exc
        world = cls(
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
        world = cls(
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
        # The civilization's derived systems, restored where the
        # snapshot carries them (S38). A world saved before these
        # existed restores without them rather than failing.
        world._restore_derived(data)
        return world

    def _restore_derived(self, data: dict) -> None:
        """Rebuild the derived systems from their serialized forms."""
        from app.simulation.budget import Budget
        from app.simulation.games import GameSession
        from app.simulation.settlement import Road, Settlement
        from app.simulation.technology import Pattern, Recipe

        for actor_id, ledger in (data.get("resources") or {}).items():
            self._resources[int(actor_id)] = dict(ledger)
        for structure in data.get("structures") or []:
            self._structures[structure["id"]] = Structure(
                id=structure["id"],
                owner=structure.get("owner"),
                purpose=structure.get("purpose"),
                components=list(structure.get("components") or []),
            )
        for component in (data.get("structure_of") or {}).items():
            self._structure_of[int(component[0])] = component[1]
        for settlement_data in data.get("settlements") or []:
            settlement = Settlement(
                id=settlement_data["id"],
                name=settlement_data["name"],
                founder_id=settlement_data["founder_id"],
                population_id=settlement_data.get("population_id"),
                founded_tick=settlement_data.get("founded_tick", 0),
                center=Position.from_dict(settlement_data["center"]),
                members=set(settlement_data.get("members") or []),
                home_ids=list(settlement_data.get("home_ids") or []),
                storage_ids=list(settlement_data.get("storage_ids") or []),
                zones={
                    int(zone["object_id"]): zone["resource"]
                    for zone in (settlement_data.get("zones") or [])
                },
                storage=dict(settlement_data.get("storage") or {}),
                road_ids=list(settlement_data.get("road_ids") or []),
            )
            self._settlements[settlement.id] = settlement
        for road_data in data.get("roads") or []:
            road = Road(
                id=road_data["id"],
                settlement_id=road_data["settlement_id"],
                owner_id=road_data["owner_id"],
                cells=[Position.from_dict(cell) for cell in road_data.get("cells") or []],
                created_tick=road_data.get("created_tick", 0),
            )
            self._roads[road.id] = road
        for object_id, settlement_id in (data.get("zones") or {}).items():
            self._zones[int(object_id)] = settlement_id
        self._next_settlement_id = max(self._settlements, default=0) + 1
        self._next_road_id = max(self._roads, default=0) + 1

        for game in data.get("games") or []:
            self._games[game["id"]] = dict(game)
        self._next_game_id = max(self._games, default=0) + 1
        for session_data in data.get("sessions") or []:
            session = GameSession(
                id=session_data["id"],
                name=session_data["name"],
                rules=session_data["rules"],
                players=list(session_data.get("players") or []),
                state=dict(session_data.get("state") or {}),
                points={int(k): v for k, v in (session_data.get("points") or {}).items()},
                turn_index=session_data.get("turn_index", 0),
                rounds_completed=session_data.get("rounds_completed", 0),
                status=session_data.get("status", "open"),
                winner=session_data.get("winner"),
                win_reason=session_data.get("win_reason"),
                history=list(session_data.get("history") or []),
            )
            self._sessions[session.id] = session
        self._next_session_id = max(self._sessions, default=0) + 1

        for recipe_data in data.get("recipes") or []:
            recipe = Recipe(
                name=recipe_data["name"],
                inputs=recipe_data.get("inputs") or {},
                produces=recipe_data["produces"],
                description=recipe_data.get("description", ""),
            )
            self._recipes[recipe.name] = recipe
        for pattern_data in data.get("patterns") or []:
            pattern = Pattern(
                name=pattern_data["name"],
                blocks=tuple(tuple(block) for block in pattern_data.get("blocks") or ()),
                description=pattern_data.get("description", ""),
            )
            self._patterns[pattern.name] = pattern
        for entity_id, names in (data.get("known_recipes") or {}).items():
            self._known_recipes[int(entity_id)] = set(names)
        for entity_id, names in (data.get("known_patterns") or {}).items():
            self._known_patterns[int(entity_id)] = set(names)

        for team_id, members in (data.get("teams") or {}).items():
            self._teams[int(team_id)] = set(members)
        for follower, target in (data.get("following") or {}).items():
            self._following[int(follower)] = target
        for entity_id, population_id in (data.get("populations") or {}).items():
            self._entity_populations[int(entity_id)] = population_id
        for entity_id, ledger in (data.get("budgets") or {}).items():
            self._budgets[int(entity_id)] = _budget_from_ledger(ledger)
        if data.get("experiment_budget"):
            self._experiment_budget = _budget_from_ledger(data["experiment_budget"])
        for speech in data.get("speeches") or []:
            self._speeches.append(
                (
                    speech["speaker"],
                    Position.from_dict(speech["position"]),
                    speech["message"],
                    speech.get("tick", 0),
                )
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

    # ------------------------------------------------------------------
    # Settlements (S30)
    # ------------------------------------------------------------------

    @property
    def settlements(self) -> list[Settlement]:
        """Every settlement, in founding order."""
        return [self._settlements[i] for i in sorted(self._settlements)]

    @property
    def roads(self) -> list[Road]:
        """Every road, in creation order."""
        return [self._roads[i] for i in sorted(self._roads)]

    def settlement(self, settlement_id: int) -> Settlement | None:
        return self._settlements.get(settlement_id)

    def settlement_of(self, entity_id: int) -> Settlement | None:
        """The settlement this entity belongs to, if any."""
        for settlement in self._settlements.values():
            if settlement.is_member(entity_id):
                return settlement
        return None

    def settlement_holding(self, structure_id: int) -> Settlement | None:
        """The settlement that counts this structure as its own."""
        for settlement in self._settlements.values():
            if structure_id in settlement.home_ids or structure_id in settlement.storage_ids:
                return settlement
        return None

    def zone_claimer(self, object_id: int) -> int | None:
        """The settlement holding a resource zone on this object."""
        return self._zones.get(object_id)

    def is_settlement_member(self, entity_id: int, settlement_id: int) -> bool:
        settlement = self._settlements.get(settlement_id)
        return settlement is not None and settlement.is_member(entity_id)

    def found_settlement(self, actor_id: int, name: str, structure_id: int) -> Settlement:
        """Found a settlement on a structure: identity, founder, home.

        The structure must belong to nobody yet, and the founder must
        not already belong to one — a community has one home people.
        The settlement's centre is the structure's centre, which is
        what its extent is measured from.
        """
        if actor_id not in self._entities:
            raise ValueError(f"unknown actor {actor_id!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("a settlement needs a name")
        name = name.strip()
        if any(s.name == name for s in self._settlements.values()):
            raise ValueError(f"a settlement named {name!r} already stands")
        if self.settlement_of(actor_id) is not None:
            raise ValueError(f"actor {actor_id} already belongs to a settlement")
        if self.settlement_holding(structure_id) is not None:
            raise ValueError(f"structure {structure_id} already belongs to a settlement")
        structure = self._structures.get(structure_id)
        if structure is None:
            raise ValueError(f"unknown structure {structure_id!r}")
        if not self._is_adjacent_to_structure(actor_id, structure_id):
            raise ValueError(f"actor {actor_id} is not beside structure {structure_id}")

        population_id = self._entity_populations.get(actor_id)
        settlement = Settlement(
            id=self._next_settlement_id,
            name=name,
            founder_id=actor_id,
            population_id=population_id,
            founded_tick=self.tick,
            center=self._structure_center(structure_id),
        )
        self._next_settlement_id += 1
        settlement.members.add(actor_id)
        if structure.purpose is None:
            structure.purpose = PURPOSE_HOME
        if structure.purpose == PURPOSE_STORAGE:
            settlement.storage_ids.append(structure_id)
        else:
            settlement.home_ids.append(structure_id)
        self._settlements[settlement.id] = settlement
        self._add_event(
            EventTypes.SETTLEMENT_FOUNDED,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": name,
                "structure_id": structure_id,
                "population_id": population_id,
                "center": settlement.center.to_dict(),
            },
        )
        return settlement

    def join_settlement(self, actor_id: int, settlement_id: int) -> Settlement:
        """Join a settlement: your people's community, or none.

        Membership follows population identity — the boundary S27 drew.
        An agent already belonging to a settlement stays put.
        """
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if actor_id not in self._entities:
            raise ValueError(f"unknown actor {actor_id!r}")
        if settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} already belongs to {settlement.name!r}")
        existing = self.settlement_of(actor_id)
        if existing is not None:
            raise ValueError(f"actor {actor_id} already belongs to {existing.name!r}")
        my_population = self._entity_populations.get(actor_id)
        if (
            settlement.population_id is not None
            and my_population is not None
            and my_population != settlement.population_id
        ):
            raise ValueError(
                f"actor {actor_id} is not of the people who founded {settlement.name!r}"
            )
        settlement.members.add(actor_id)
        self._add_event(
            EventTypes.SETTLEMENT_JOINED,
            actor_id=actor_id,
            payload={"settlement_id": settlement.id, "name": settlement.name},
        )
        return settlement

    def adopt_structure(self, actor_id: int, settlement_id: int, structure_id: int) -> dict:
        """A member claims a standing structure for its settlement.

        The member must be beside it and it must stand within the
        settlement's extent — a village does not reach the other side
        of the world. Its purpose decides what it becomes: a home, or
        shared storage.
        """
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        structure = self._structures.get(structure_id)
        if structure is None:
            raise ValueError(f"unknown structure {structure_id!r}")
        if self.settlement_holding(structure_id) is not None:
            raise ValueError(f"structure {structure_id} already belongs to a settlement")
        if not self._is_adjacent_to_structure(actor_id, structure_id):
            raise ValueError(f"actor {actor_id} is not beside structure {structure_id}")
        center = self._structure_center(structure_id)
        if self._distance(center, settlement.center) > SETTLEMENT_EXTENT:
            raise ValueError(
                f"structure {structure_id} stands outside {settlement.name!r}'s extent"
            )
        purpose = structure.purpose
        if purpose == PURPOSE_STORAGE:
            settlement.storage_ids.append(structure_id)
            kind = "storage"
        else:
            if purpose is None:
                structure.purpose = PURPOSE_HOME
            settlement.home_ids.append(structure_id)
            kind = "home"
        self._add_event(
            EventTypes.SETTLEMENT_GROWN,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "structure_id": structure_id,
                "kind": kind,
            },
        )
        return {"structure_id": structure_id, "kind": kind}

    def maybe_adopt(self, actor_id: int, structure_id: int) -> dict | None:
        """The settlement grows under its own builders' hands (S30).

        A member raising a structure inside the settlement's extent
        counts it automatically — a population that builds together
        grows a village without being told to. Returns what was
        adopted, or None.
        """
        settlement = self.settlement_of(actor_id)
        if settlement is None:
            return None
        structure = self._structures.get(structure_id)
        if structure is None or self.settlement_holding(structure_id) is not None:
            return None
        center = self._structure_center(structure_id)
        if self._distance(center, settlement.center) > SETTLEMENT_EXTENT:
            return None
        try:
            return self.adopt_structure(actor_id, settlement.id, structure_id)
        except ValueError:
            return None

    def deposit(self, actor_id: int, settlement_id: int, resource: str, amount: int) -> dict:
        """Bank a resource into the settlement's shared storage."""
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("amount must be a positive integer")
        if not self._beside_storage(actor_id, settlement):
            raise ValueError(f"actor {actor_id} is not beside {settlement.name!r}'s storage")
        if self.resource_count(actor_id, resource) < amount:
            raise ValueError(
                f"actor {actor_id} carries {self.resource_count(actor_id, resource)} "
                f"{resource}, not {amount}"
            )
        self.spend_resource(actor_id, resource, amount)
        settlement.storage[resource] = settlement.storage.get(resource, 0) + amount
        self._add_event(
            EventTypes.SETTLEMENT_STORAGE,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "kind": "deposit",
                "resource": resource,
                "amount": amount,
                "balance": dict(settlement.storage),
            },
        )
        return {"resource": resource, "amount": amount, "balance": dict(settlement.storage)}

    def withdraw(self, actor_id: int, settlement_id: int, resource: str, amount: int) -> dict:
        """Draw a resource back out of the shared storage."""
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("amount must be a positive integer")
        if not self._beside_storage(actor_id, settlement):
            raise ValueError(f"actor {actor_id} is not beside {settlement.name!r}'s storage")
        if settlement.storage.get(resource, 0) < amount:
            raise ValueError(
                f"{settlement.name!r} holds {settlement.storage.get(resource, 0)} "
                f"{resource}, not {amount}"
            )
        settlement.storage[resource] -= amount
        if settlement.storage[resource] <= 0:
            del settlement.storage[resource]
        self.credit_resource(actor_id, resource, amount)
        self._add_event(
            EventTypes.SETTLEMENT_STORAGE,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "kind": "withdrawal",
                "resource": resource,
                "amount": amount,
                "balance": dict(settlement.storage),
            },
        )
        return {"resource": resource, "amount": amount, "balance": dict(settlement.storage)}

    def claim_zone(self, actor_id: int, settlement_id: int, resource: str, object_id: int) -> dict:
        """Claim a resource source for the settlement: the Void's first
        property. Outsiders are refused at the source; members gather
        freely."""
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        obj = self._objects.get(object_id)
        if obj is None:
            raise ValueError(f"unknown object {object_id!r}")
        if obj.position is None:
            raise ValueError(f"object {object_id} is carried, not a source in the world")
        if obj.properties.get("resource") != resource:
            raise ValueError(f"object {object_id} yields {obj.properties.get('resource')!r}, not {resource!r}")
        if not self._is_adjacent_to_object(actor_id, obj.position):
            raise ValueError(f"actor {actor_id} is not beside object {object_id}")
        holder = self._zones.get(object_id)
        if holder is not None:
            held = self._settlements.get(holder)
            held_by = held.name if held else f"settlement {holder}"
            raise ValueError(f"object {object_id} is already claimed by {held_by}")
        self._zones[object_id] = settlement.id
        settlement.zones[object_id] = resource
        self._add_event(
            EventTypes.ZONE_CLAIMED,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "resource": resource,
                "object_id": object_id,
                "position": obj.position.to_dict(),
            },
        )
        return {"object_id": object_id, "resource": resource}

    def release_zone(self, actor_id: int, settlement_id: int, object_id: int) -> dict:
        """Let a claimed source go."""
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        if self._zones.get(object_id) != settlement.id:
            raise ValueError(f"object {object_id} is not held by {settlement.name!r}")
        self._zones.pop(object_id, None)
        settlement.zones.pop(object_id, None)
        self._add_event(
            EventTypes.ZONE_CLAIMED,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "resource": None,
                "object_id": object_id,
                "released": True,
            },
        )
        return {"object_id": object_id, "released": True}

    def pave(self, actor_id: int, settlement_id: int, cells: list[dict]) -> dict:
        """Lay road: cells on the ground that block nothing.

        A road is a record, not a wall — you can walk it. Cells join
        the settlement's newest road when they touch it, so paving a
        path builds one continuous road rather than a scatter.
        """
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            raise ValueError(f"unknown settlement {settlement_id!r}")
        if not settlement.is_member(actor_id):
            raise ValueError(f"actor {actor_id} is not a member of {settlement.name!r}")
        if not isinstance(cells, list) or not cells:
            raise ValueError("paving needs at least one cell")
        parsed = []
        for cell in cells:
            x, y = cell["x"], cell["y"]
            if not isinstance(x, int) or not isinstance(y, int):
                raise ValueError(f"road cells must be integer coordinates, got {cell!r}")
            parsed.append(Position(x, y))
        position = self._entities.get(actor_id)
        if position is None:  # pragma: no cover - membership implies presence
            raise ValueError(f"unknown actor {actor_id!r}")
        for cell in parsed:
            if not self.in_bounds(cell) or self.terrain_at(cell) is not Terrain.FLOOR:
                raise ValueError(f"road cell ({cell.x},{cell.y}) is not floor")
            if cell in self._occupancy:
                raise ValueError(f"road cell ({cell.x},{cell.y}) holds an object")
            if self._distance(cell, settlement.center) > SETTLEMENT_EXTENT:
                raise ValueError(
                    f"road cell ({cell.x},{cell.y}) stands outside {settlement.name!r}'s extent"
                )
            if cell != position and not self._is_adjacent(position, cell):
                raise ValueError(f"road cell ({cell.x},{cell.y}) is out of reach")
            position = cell
        laid = []
        for cell in parsed:
            road_id = self._road_touching(settlement.id, cell)
            if road_id is None:
                road = Road(
                    id=self._next_road_id,
                    settlement_id=settlement.id,
                    owner_id=actor_id,
                    created_tick=self.tick,
                )
                self._next_road_id += 1
                self._roads[road.id] = road
                settlement.road_ids.append(road.id)
                road_id = road.id
            road = self._roads[road_id]
            if cell not in road.cells:
                road.cells.append(cell)
            laid.append(cell.to_dict())
        self._add_event(
            EventTypes.ROAD_LAID,
            actor_id=actor_id,
            payload={
                "settlement_id": settlement.id,
                "name": settlement.name,
                "cells": laid,
                "road_ids": list(settlement.road_ids),
            },
        )
        return {"cells": laid, "roads": len(settlement.road_ids)}

    # --- settlement helpers ---

    def settlement_view(self, actor_id: int) -> dict | None:
        """A member's view of its settlement (S30): identity, the shared
        storage it can draw on, the zones it holds, and its people.

        None for everyone outside — a home you cannot see is not a
        home.
        """
        settlement = self.settlement_of(actor_id)
        if settlement is None:
            return None
        zones = []
        for object_id, resource in settlement.zones.items():
            obj = self._objects.get(object_id)
            zones.append(
                {
                    "object_id": object_id,
                    "resource": resource,
                    "position": obj.position.to_dict() if obj and obj.position else None,
                }
            )
        return {
            "id": settlement.id,
            "name": settlement.name,
            "role": settlement.role_of(actor_id),
            "population_id": settlement.population_id,
            "members": sorted(settlement.members),
            "homes": len(settlement.home_ids),
            "storage": len(settlement.storage_ids),
            "roads": len(settlement.road_ids),
            "contents": dict(settlement.storage),
            "zones": zones,
        }

    def _road_touching(self, settlement_id: int, cell: Position) -> int | None:
        for road in self._roads.values():
            if road.settlement_id != settlement_id:
                continue
            if cell in road.cells or any(
                self._is_adjacent(cell, existing) for existing in road.cells
            ):
                return road.id
        return None

    def _is_adjacent(self, first: Position, second: Position) -> bool:
        return (
            abs(first.x - second.x) + abs(first.y - second.y) == 1
        )

    def _is_adjacent_to_structure(self, actor_id: int, structure_id: int) -> bool:
        position = self._entities.get(actor_id)
        structure = self._structures.get(structure_id)
        if position is None or structure is None:
            return False
        return any(
            self._is_adjacent(position, self._objects[object_id].position)
            for object_id in structure.components
            if self._objects.get(object_id) and self._objects[object_id].position is not None
        )

    def _is_adjacent_to_object(self, actor_id: int, position: Position) -> bool:
        mine = self._entities.get(actor_id)
        return mine is not None and self._is_adjacent(mine, position)

    def _beside_storage(self, actor_id: int, settlement: Settlement) -> bool:
        return any(
            self._is_adjacent_to_structure(actor_id, structure_id)
            for structure_id in settlement.storage_ids
        )

    def _structure_center(self, structure_id: int) -> Position:
        structure = self._structures.get(structure_id)
        positions = [
            self._objects[object_id].position
            for object_id in structure.components
            if self._objects.get(object_id) and self._objects[object_id].position is not None
        ]
        if not positions:  # pragma: no cover - structures hold placed blocks
            return Position(0, 0)
        return Position(
            round(sum(p.x for p in positions) / len(positions)),
            round(sum(p.y for p in positions) / len(positions)),
        )

    def _distance(self, first: Position, second: Position) -> int:
        return abs(first.x - second.x) + abs(first.y - second.y)

    # ------------------------------------------------------------------
    # Games (S31)
    # ------------------------------------------------------------------

    @property
    def games(self) -> list[dict]:
        """Every proposed game, in proposal order."""
        return [self._games[i] for i in sorted(self._games)]

    @property
    def sessions(self) -> list[GameSession]:
        """Every table, in opening order."""
        return [self._sessions[i] for i in sorted(self._sessions)]

    def session(self, session_id: int) -> GameSession | None:
        return self._sessions.get(session_id)

    def propose_game(self, inventor_id: int | None, rules: dict) -> dict:
        """Put a game's rules on the table: validated data, never code.

        The validator is the gate — unknown keys, undeclared state and
        unopenable games are refused with their reasons, so whatever
        passes is playable by construction. The inventor is whoever
        proposed it: an agent, the participant, or nobody (the operator).
        """
        errors = validate_rules(rules)
        if errors:
            raise ValueError(f"unplayable rules: {'; '.join(errors)}")
        game = {
            "id": self._next_game_id,
            "name": rules["name"],
            "rules": {**rules, "setup": dict(rules["setup"])},
            "inventor_id": inventor_id,
            "proposed_tick": self.tick,
        }
        self._next_game_id += 1
        self._games[game["id"]] = game
        self._add_event(
            EventTypes.GAME_PROPOSED,
            actor_id=inventor_id,
            payload={
                "game_id": game["id"],
                "name": game["name"],
                "players": rules["players"],
            },
        )
        return game

    def open_session(self, game_id: int) -> GameSession:
        """Open a table for a proposed game; players join after."""
        game = self._games.get(game_id)
        if game is None:
            raise ValueError(f"unknown game {game_id!r}")
        session = GameSession(
            id=self._next_session_id,
            name=game["name"],
            rules={**game["rules"], "setup": dict(game["rules"]["setup"])},
            state=dict(game["rules"]["setup"]),
        )
        self._next_session_id += 1
        self._sessions[session.id] = session
        return session

    def join_session(self, session_id: int, entity_id: int) -> GameSession:
        """Take a seat: the table fills in join order, then play begins."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"unknown session {session_id!r}")
        if entity_id not in self._entities:
            raise ValueError(f"unknown entity {entity_id!r}")
        if entity_id in session.players:
            raise ValueError(f"entity {entity_id} already sits at game {session.id}")
        # Capacity before status: a full table that has already begun
        # says "no open seat" rather than "already playing" — the seat
        # is what the joiner is asking about.
        if len(session.players) >= session.seats:
            raise ValueError(f"game {session.id} has no open seat")
        if session.status != "open":
            raise ValueError(f"game {session.id} is already {session.status}")
        session.players.append(entity_id)
        session.points.setdefault(entity_id, 0)
        if len(session.players) >= session.seats:
            session.status = "playing"
            self._add_event(
                EventTypes.GAME_STARTED,
                payload={
                    "session_id": session.id,
                    "name": session.name,
                    "players": list(session.players),
                },
            )
        return session

    def play_move(self, session_id: int, entity_id: int, move_name: str) -> dict:
        """Play a move: the interpreter's decision, recorded either way
        the turn goes."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"unknown session {session_id!r}")
        outcome = session.play(entity_id, move_name, self.tick)
        self._add_event(
            EventTypes.GAME_MOVE,
            actor_id=entity_id,
            payload={
                "session_id": session.id,
                "name": session.name,
                "move": move_name,
                "state": dict(outcome["state"]),
            },
        )
        if outcome["winner"] is not None:
            self._add_event(
                EventTypes.GAME_OVER,
                actor_id=outcome["winner"],
                payload={
                    "session_id": session.id,
                    "name": session.name,
                    "winner": outcome["winner"],
                    "win_reason": outcome["win_reason"],
                    "points": dict(outcome["points"]),
                },
            )
        return outcome

    def games_for(self, entity_id: int) -> list[dict]:
        """The tables this entity sits at, as a player sees them: whose
        turn it is, what is legal now, the score, and who won."""
        view = []
        for session in self.sessions:
            if entity_id not in session.players:
                continue
            view.append(
                {
                    "session_id": session.id,
                    "name": session.name,
                    "status": session.status,
                    "your_turn": session.current_player == entity_id,
                    "legal_moves": session.legal_moves(entity_id),
                    "state": dict(session.state),
                    "points": dict(session.points),
                    "players": list(session.players),
                    "winner": session.winner,
                    "win_reason": session.win_reason,
                }
            )
        return view

    # ------------------------------------------------------------------
    # Compute budgets (S33)
    # ------------------------------------------------------------------

    def budget_of(self, entity_id: int) -> Budget:
        """An entity's compute ledger, created on first sight."""
        if entity_id not in self._budgets:
            self._budgets[entity_id] = Budget()
        return self._budgets[entity_id]

    def set_budget(self, entity_id: int, **limits) -> Budget:
        """Cap an entity's compute by kind (None leaves a kind open)."""
        budget = self.budget_of(entity_id)
        for kind, value in limits.items():
            budget.limits[kind] = _clean_budget_value(kind, value)
        return budget

    @property
    def experiment_budget(self) -> Budget:
        """The run's shared budget: every agent's spend draws on it."""
        if self._experiment_budget is None:
            self._experiment_budget = Budget()
        return self._experiment_budget

    def _spend_budget(self, entity_id: int, kind: str, amount: float = 1) -> None:
        """Charge both ledgers that apply: the entity's, then the
        experiment's. The experiment's ceiling binds even when the
        entity's own kind is open — a run cannot outspend its budget."""
        budget = self.budget_of(entity_id)
        budget.spend(kind, amount)
        if self._experiment_budget is not None:
            # Cap-less experiments spend nothing anywhere.
            if self._experiment_budget.limits.get(kind) is not None:
                self._experiment_budget.spend(kind, amount)

    def budget_view(self, entity_id: int) -> dict:
        """What an entity may still spend, as the observation sees it.

        The experiment's shared ceiling rides along as ``experiment``:
        only the kinds it actually caps, so a world without budgets
        shows no study-wide ledger at all.
        """
        budget = self.budget_of(entity_id)
        view = budget.to_dict()
        if self._experiment_budget is not None:
            ledger = self._experiment_budget.to_dict()
            view["experiment"] = {
                kind: ledger[kind]
                for kind in KINDS
                if self._experiment_budget.limits[kind] is not None
            }
        return view

    def __repr__(self) -> str:
        return (
            f"World(seed={self.seed!r}, {self.width}x{self.height}, "
            f"tick={self.tick}, objects={len(self._objects)})"
        )
