"""Populations: groups of agents with spawn rules (S27).

An engine is one world; a *population* is a group inside it — with a
name, a spawn rule, membership, and the social facts (family, teams,
following) that relate its members. Populations are the step beyond
one lineage: several groups can inhabit the Void at once, each with
its own rules, and each visible to the others.

The manager is deliberately thin. It owns no agent state — the engine
does — and mutates the world only through the engine's spawn path. A
population's *rule* is data (`SpawnRule`), so a world can be created
from a list of rules, and a rule can arrive later into a live world.

Spawn rules mean three things here:
- **founding size** — how many members a population starts with, and
  which scripted minds rotate through those places;
- **a carry capacity** — `max_members` caps the population: births
  beyond it are refused by the engine (a `BirthError`), so a group
  cannot grow past its rule;
- **top-up** — a population can replace its losses: when it falls
  below its founding size, new members arrive on their own.

Relationships are derived facts, not stored state: family from the
lineage (parent/child/sibling), teams and following from the world,
and population membership itself. Two agents of different populations
are strangers to each other — the boundary that makes groups groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import ForagerPolicy, GathererPolicy, WanderPolicy
from app.simulation.world import Position, World

# Scripted minds a rule can name. "model" is not scripted: it needs a
# factory from the registry (one provider per world), so it is missing
# from the default one on purpose.
SCRIPTED_POLICIES = ("wander", "forage", "gather")


def default_policy(name: str):
    """The scripted policy a name resolves to."""
    if name == "wander":
        return WanderPolicy()
    if name == "forage":
        return ForagerPolicy()
    if name == "gather":
        return GathererPolicy("wood")
    raise ValueError(f"unknown scripted policy {name!r}; expected one of {SCRIPTED_POLICIES}")


def default_agent_factory(name: str, index: int) -> Agent:
    """The default member of a population: a scripted mind at radius 2.

    The gatherer keeps the registry's wider radius (4): it needs to see
    the resource it walks to. `agent_id` is a placeholder — the manager
    numbers agents at spawn time.
    """
    radius = 4 if name == "gather" else 2
    return Agent(agent_id=-1, policy=default_policy(name), observation_radius=radius)


@dataclass(frozen=True)
class SpawnRule:
    """The rule a population lives by, as data.

    `members` is both the founding size and the top-up target.
    `spawn_zone` is an inclusive `(x0, y0, x1, y1)` rect; founding
    members appear inside it, and a zone that cannot fit the founding
    group is an error rather than a silent overflow. `stipend` credits
    resources to every member as it arrives (granted wood, like the
    arms race's builders).
    """

    name: str
    members: int = 1
    policies: tuple[str, ...] = ("wander",)
    spawn_zone: tuple[int, int, int, int] | None = None
    max_members: int | None = None
    top_up: bool = False
    stipend: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a population needs a non-empty name")
        if not isinstance(self.members, int) or self.members < 0:
            raise ValueError(f"members must be >= 0, got {self.members!r}")
        if not self.policies:
            raise ValueError("a population needs at least one policy")
        if self.max_members is not None:
            if not isinstance(self.max_members, int) or self.max_members < self.members:
                raise ValueError(
                    f"max_members ({self.max_members!r}) must be >= members ({self.members})"
                )
        if self.spawn_zone is not None:
            zone = self.spawn_zone
            if len(zone) != 4 or not all(isinstance(v, int) for v in zone):
                raise ValueError(f"spawn_zone must be 4 integers, got {zone!r}")
            x0, y0, x1, y1 = zone
            if x0 > x1 or y0 > y1:
                raise ValueError(f"spawn_zone must be (x0, y0, x1, y1) with x0<=x1, y0<=y1, got {zone!r}")
        if not isinstance(self.stipend, dict):
            raise ValueError("stipend must be a mapping of resource kind to amount")
        for kind, amount in self.stipend.items():
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise ValueError(f"stipend amounts must be non-negative integers, got {kind}={amount!r}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "members": self.members,
            "policies": list(self.policies),
            "spawn_zone": list(self.spawn_zone) if self.spawn_zone else None,
            "max_members": self.max_members,
            "top_up": self.top_up,
            "stipend": dict(self.stipend),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpawnRule":
        data = dict(data)
        data["policies"] = tuple(data.get("policies") or ("wander",))
        data["spawn_zone"] = (
            tuple(data["spawn_zone"]) if data.get("spawn_zone") else None
        )
        return cls(
            name=data["name"],
            members=data.get("members", 1),
            policies=data["policies"],
            spawn_zone=data["spawn_zone"],
            max_members=data.get("max_members"),
            top_up=bool(data.get("top_up", False)),
            stipend=dict(data.get("stipend") or {}),
        )


@dataclass
class Population:
    """One population's runtime record."""

    population_id: int
    rule: SpawnRule
    founded_tick: int
    arrivals: int = 0

    def to_dict(self) -> dict:
        return {
            "population_id": self.population_id,
            "rule": self.rule.to_dict(),
            "founded_tick": self.founded_tick,
            "arrivals": self.arrivals,
        }


class PopulationManager:
    """All populations in one world, and the rules that govern them."""

    def __init__(
        self,
        engine: Engine,
        *,
        agent_factory=default_agent_factory,
        cell_hint=None,
    ) -> None:
        self._engine = engine
        self._agent_factory = agent_factory
        self._cell_hint = cell_hint
        self._populations: dict[int, Population] = {}

    @property
    def world(self) -> World:
        return self._engine.world

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, population_id: int, rule: SpawnRule | dict) -> Population:
        """Bind a rule to a population id (the engine's and the DB row's)."""
        if not isinstance(rule, SpawnRule):
            rule = SpawnRule.from_dict(rule)
        if population_id in self._populations:
            raise ValueError(f"population {population_id} is already registered")
        population = Population(
            population_id=population_id, rule=rule, founded_tick=self.world.tick
        )
        self._populations[population_id] = population
        return population

    def get(self, population_id: int) -> Population:
        population = self._populations.get(population_id)
        if population is None:
            raise ValueError(f"unknown population {population_id!r}")
        return population

    def _require(self, population_id: int) -> Population:
        return self.get(population_id)

    def __contains__(self, population_id: int) -> bool:
        return population_id in self._populations

    def __len__(self) -> int:
        return len(self._populations)

    @property
    def populations(self) -> list[Population]:
        return [self._populations[i] for i in sorted(self._populations)]

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def spawn_founding(self, population_id: int) -> list[Agent]:
        """Raise a population's founding members, in rule order.

        One `POPULATION_SPAWN` event records the founding (the members'
        own `ENTITY_ADDED` events carry the per-agent detail), so the
        timeline says when a group came to be, not just its members.
        """
        population = self._require(population_id)
        rule = population.rule
        spawned: list[Agent] = []
        for index in range(rule.members):
            agent = self._new_agent(population, index)
            cell = self._placement(rule, index)
            if cell is None:
                raise ValueError(
                    f"population {rule.name!r} has no free cell in its spawn zone "
                    f"for member {index + 1}/{rule.members}"
                )
            self._arrive(population, agent, cell)
            spawned.append(agent)
        self.world._add_event(
            EventTypes.POPULATION_SPAWN,
            payload={
                "population_id": population_id,
                "name": rule.name,
                "kind": "founding",
                "members": [agent.agent_id for agent in spawned],
                "rule": rule.to_dict(),
            },
        )
        return spawned

    def spawn_arrival(self, population_id: int) -> Agent | None:
        """One new member, if the rule and the world allow it.

        Returns None when the population is at its cap or the world has
        no free cell — a rule that cannot fire *now* is not an error.
        """
        population = self._require(population_id)
        rule = population.rule
        if not self.can_reproduce(population_id):
            return None
        index = len(self.members(population_id))
        agent = self._new_agent(population, index)
        cell = self._placement(rule, index)
        if cell is None:
            return None  # world full: the rule holds until room appears
        self._arrive(population, agent, cell)
        population.arrivals += 1
        self.world._add_event(
            EventTypes.POPULATION_SPAWN,
            payload={
                "population_id": population_id,
                "name": rule.name,
                "kind": "arrival",
                "agent_id": agent.agent_id,
            },
        )
        return agent

    def enforce_spawn_rules(self) -> list[Agent]:
        """Apply every top-up rule: a population below its size regrows.

        The host calls this each tick, so a population that loses
        members backfills itself without any operator involvement.
        """
        spawned: list[Agent] = []
        for population in self.populations:
            if not population.rule.top_up:
                continue
            for _ in range(population.rule.members):
                if len(self.members(population.population_id)) >= population.rule.members:
                    break
                agent = self.spawn_arrival(population.population_id)
                if agent is None:
                    break
                spawned.append(agent)
        return spawned

    def can_reproduce(self, population_id: int) -> bool:
        """Whether the population has room for one more member.

        Unknown populations are ungoverned (no cap): the engine's
        default population, and worlds that never registered rules.
        """
        population = self._populations.get(population_id)
        if population is None:
            return True
        cap = population.rule.max_members
        if cap is None:
            return True
        return len(self.members(population_id)) < cap

    def _new_agent(self, population: Population, index: int) -> Agent:
        rule = population.rule
        name = rule.policies[index % len(rule.policies)]
        agent = self._agent_factory(name, index)
        agent.agent_id = self._engine.next_agent_id()
        agent.population_id = population.population_id
        agent.population_size_provider = self.population_size
        return agent

    def _arrive(self, population: Population, agent: Agent, cell: Position) -> None:
        self._engine.spawn_agent(agent, cell)
        for kind, amount in population.rule.stipend.items():
            self.world.credit_resource(agent.agent_id, kind, amount)

    def _placement(self, rule: SpawnRule, index: int) -> Position | None:
        """Where this member appears: the hint first, then the rule's zone.

        The hint is the registry's placement knowledge (a gatherer
        starts beside its resource); the zone is the rule's. A zone
        that overflows the world is a rule error, not a fallback.
        """
        if self._cell_hint is not None:
            name = rule.policies[index % len(rule.policies)]
            hint = self._cell_hint(name, index)
            if hint is not None and self._is_free(hint):
                return hint
        for candidate in self._zone_cells(rule):
            if self._is_free(candidate):
                return candidate
        return None

    def _is_free(self, cell: Position) -> bool:
        world = self.world
        return (
            world.is_floor(cell)
            and world.object_at(cell) is None
            and world.entity_at(cell) is None
        )

    def _zone_cells(self, rule: SpawnRule) -> list[Position]:
        """The rule's spawn cells, row-major (interior floor only)."""
        world = self.world
        if rule.spawn_zone is None:
            x0, y0, x1, y1 = 1, 1, world.width - 2, world.height - 2
        else:
            x0, y0, x1, y1 = rule.spawn_zone
            if x0 < 0 or y0 < 0 or x1 >= world.width or y1 >= world.height:
                raise ValueError(
                    f"spawn_zone {rule.spawn_zone!r} is outside the "
                    f"{world.width}x{world.height} world"
                )
        return [Position(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]

    # ------------------------------------------------------------------
    # Membership and statistics
    # ------------------------------------------------------------------

    def members(self, population_id: int) -> list[Agent]:
        return self._engine.population(population_id)

    def population_size(self, population_id: int | None) -> int:
        return len(self._engine.population(population_id))

    def statistics(self, population_id: int | None = None):
        """One population's statistics, or every population's (by id)."""
        if population_id is not None:
            return self._statistics_for(self._require(population_id))
        return [self._statistics_for(p) for p in self.populations]

    def world_statistics(self) -> dict:
        populations = self.statistics()
        resources: dict[str, int] = {}
        for stats in populations:
            for kind, amount in stats["resources"].items():
                resources[kind] = resources.get(kind, 0) + amount
        return {
            "populations": populations,
            "totals": {
                "populations": len(populations),
                "agents": len(self._engine.agents),
                "births": sum(p["births"] for p in populations),
                "arrivals": sum(p["arrivals"] for p in populations),
                "resources": resources,
            },
        }

    def _statistics_for(self, population: Population) -> dict:
        rule = population.rule
        members = self.members(population.population_id)
        generations = [a.generation for a in members]
        resources: dict[str, int] = {}
        for agent in members:
            for kind, amount in self.world.resources(agent.agent_id).items():
                resources[kind] = resources.get(kind, 0) + amount
        return {
            "population_id": population.population_id,
            "name": rule.name,
            "size": len(members),
            "max_members": rule.max_members,
            "top_up": rule.top_up,
            "generation": {
                "min": min(generations) if generations else 0,
                "max": max(generations) if generations else 0,
                "average": round(sum(generations) / len(generations), 2) if generations else 0,
            },
            "brains": {
                "model": sum(1 for a in members if hasattr(a.policy, "refresh")),
                "scripted": sum(1 for a in members if not hasattr(a.policy, "refresh")),
            },
            "resources": resources,
            "births": sum(1 for a in members if a.parent_id is not None),
            "arrivals": population.arrivals,
            "founded_tick": population.founded_tick,
            "age_ticks": self.world.tick - population.founded_tick,
            "rule": rule.to_dict(),
        }

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def kin(self, agent_id: int) -> dict:
        """An agent's family, from the lineage: parent, children, siblings."""
        agent = self._engine.agent(agent_id)
        if agent is None:
            raise ValueError(f"unknown agent {agent_id!r}")
        siblings = []
        for other in self._engine.agents:
            if (
                other.agent_id == agent_id
                or other.parent_id is None
                or agent.parent_id is None
                or other.parent_id != agent.parent_id
            ):
                continue
            siblings.append(other.agent_id)
        return {
            "agent_id": agent_id,
            "population_id": agent.population_id,
            "parent": agent.parent_id,
            "children": [c.agent_id for c in self._engine.agents if c.parent_id == agent_id],
            "siblings": sorted(siblings),
        }

    def relationship(self, agent_id: int, other_id: int) -> str:
        """How `agent_id` stands to `other_id`.

        Kin first (family is the oldest relation), then following (who
        walks with whom), then teammates, then population membership,
        then strangers — the boundary that makes groups groups.
        """
        agent = self._engine.agent(agent_id)
        other = self._engine.agent(other_id)
        if agent is None or other is None:
            raise ValueError(f"unknown agent pair ({agent_id!r}, {other_id!r})")
        if agent.parent_id == other.agent_id:
            return "parent"
        if other.parent_id == agent.agent_id:
            return "child"
        if agent.parent_id is not None and agent.parent_id == other.parent_id:
            return "sibling"
        world = self.world
        if world.follow_target(agent_id) == other_id:
            return "leader"
        if world.follow_target(other_id) == agent_id:
            return "follower"
        if any(mate["id"] == other_id for mate in world.teammates_of(agent_id)):
            return "teammate"
        if agent.population_id is not None and agent.population_id == other.population_id:
            return "neighbor"
        return "stranger"

    def relationships(self, agent_id: int) -> list[dict]:
        """Every other agent in the world, as this agent relates to them."""
        agent = self._engine.agent(agent_id)
        if agent is None:
            raise ValueError(f"unknown agent {agent_id!r}")
        here = agent.position
        relations = []
        for other in self._engine.agents:
            if other.agent_id == agent_id:
                continue
            there = other.position
            relations.append(
                {
                    "agent_id": other.agent_id,
                    "kind": self.relationship(agent_id, other.agent_id),
                    "population_id": other.population_id,
                    "generation": other.generation,
                    "position": there.to_dict() if there else None,
                    "distance": (
                        abs(there.x - here.x) + abs(there.y - here.y)
                        if there and here
                        else None
                    ),
                }
            )
        return relations
