"""S09 — birth and generation at the engine level.

The roadmap's verification is a sequential lineage: 0 → 1 → 2 → … → 100
with every parent/child relationship and generation number checked.
That chain is driven here through `Engine.create_child` — the engine
stays pure, so no database is involved.
"""

import pytest

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.errors import BirthError
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World


def _flat_engine(size: int = 24, population_id: int | None = None) -> Engine:
    """An all-floor world with no border walls — room to make a lineage."""
    terrain = [[Terrain.FLOOR] * size for _ in range(size)]
    return Engine(World("flat", size, size, terrain=terrain), population_id=population_id)


def _spawn(engine: Engine, agent_id: int, x: int, y: int, **kwargs) -> Agent:
    agent = Agent(agent_id=agent_id, policy=WanderPolicy(), **kwargs)
    engine.spawn_agent(agent, Position(x, y))
    return agent


class TestCreateChild:
    def test_child_is_linked_and_placed_north(self):
        engine = _flat_engine()
        parent = _spawn(engine, 1, 2, 2)

        child = engine.create_child(1)

        assert child.agent_id == 2
        assert child.parent_id == 1
        assert child.generation == 1
        assert child.position == Position(2, 1)  # first free N → E → S → W
        assert child.status == "alive"
        assert parent.status == "alive"

    def test_birth_event_records_the_lineage(self):
        engine = _flat_engine(population_id=7)
        _spawn(engine, 1, 2, 2)

        engine.create_child(1, inheritance={"message": "go west, young one"})

        born = [e for e in engine.world.events if e.type == EventTypes.AGENT_BORN]
        assert len(born) == 1
        payload = born[0].payload
        assert payload["parent_id"] == 1
        assert payload["child_id"] == 2
        assert payload["generation"] == 1
        assert payload["population_id"] == 7
        assert payload["position"] == {"x": 2, "y": 1}
        assert payload["inheritance"] == {
            "traits": {},
            "knowledge": [],
            "message": "go west, young one",
            "cultural_artifacts": [],
        }
        assert born[0].actor_id == 1
        assert born[0].target_id == 2

    def test_inheritance_package_goal_and_message(self):
        engine = _flat_engine()
        parent = _spawn(engine, 1, 2, 2, goal="find food")

        child = engine.create_child(1, inheritance={"message": "eat well"})

        assert child.goal == "find food"  # the parent's goal starts the child's
        entry = child.memory.recent()[0]
        assert entry["action"] == {"kind": "inheritance", "from": 1}
        assert entry["reason"] == "eat well"  # the parent -> child message
        assert entry["goal"] == "find food"

    def test_explicit_position_honored(self):
        engine = _flat_engine()
        _spawn(engine, 1, 2, 2)

        child = engine.create_child(1, position=Position(3, 3))

        assert child.position == Position(3, 3)

    def test_explicit_policy_used(self):
        engine = _flat_engine()
        _spawn(engine, 1, 2, 2)
        policy = WanderPolicy()

        child = engine.create_child(1, policy=policy)

        assert child.policy is policy

    def test_default_policy_is_scripted(self):
        engine = _flat_engine()
        _spawn(engine, 1, 2, 2)

        child = engine.create_child(1)

        assert isinstance(child.policy, WanderPolicy)

    def test_unknown_parent_rejected(self):
        engine = _flat_engine()
        with pytest.raises(ValueError, match="unknown parent"):
            engine.create_child(99)

    def test_dead_parent_rejected(self):
        engine = _flat_engine()
        parent = _spawn(engine, 1, 2, 2)
        parent.status = "dead"
        with pytest.raises(BirthError, match="not alive"):
            engine.create_child(1)

    def test_no_room_rejected_and_nothing_half_applied(self):
        # BirthError is for a world with no free cell anywhere — not
        # for a full neighbourhood (that search widens).
        engine = Engine(
            World("full", 3, 3, terrain=[[Terrain.FLOOR] * 3 for _ in range(3)])
        )
        _spawn(engine, 1, 1, 1)
        agent_id = 2
        for y in range(3):
            for x in range(3):
                if (x, y) != (1, 1):
                    _spawn(engine, agent_id, x, y)
                    agent_id += 1

        with pytest.raises(BirthError, match="no free cell"):
            engine.create_child(1)

        assert len(engine.agents) == 9  # the full world, no child
        assert not [e for e in engine.world.events if e.type == EventTypes.AGENT_BORN]

    def test_boxed_in_parent_births_to_the_nearest_free_cell(self):
        # The neighbourhood is full; the ring search widens instead of
        # failing (the API's birth route drove 100 births before this).
        engine = Engine(
            World("wide", 9, 9, terrain=[[Terrain.FLOOR] * 9 for _ in range(9)])
        )
        _spawn(engine, 1, 4, 4)
        for i, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
            _spawn(engine, i + 2, 4 + dx, 4 + dy)

        child = engine.create_child(1)

        assert child.status == "alive"
        assert child.position not in [Position(4, 3), Position(5, 4), Position(4, 5), Position(3, 4)]
        # Deterministic: the nearest free cell, clockwise from the north
        # — the parent's north-east diagonal, since the four orthogonal
        # neighbours are occupied.
        assert child.position == Position(5, 3)


class TestSequentialLineage:
    def test_chain_to_generation_100(self):
        # The roadmap's exact verification: 0 -> 1 -> 2 -> ... -> 100.
        engine = _flat_engine()
        founder = _spawn(engine, 1, 1, 1)

        parent = founder
        for expected_generation in range(1, 101):
            child = engine.create_child(parent.agent_id)
            assert child.generation == expected_generation
            assert child.parent_id == parent.agent_id
            parent = child

        generations = [agent.generation for agent in engine.agents]
        assert generations == list(range(101))
        born = [e for e in engine.world.events if e.type == EventTypes.AGENT_BORN]
        assert [e.payload["generation"] for e in born] == list(range(1, 101))

    def test_ancestors_walks_the_chain_to_the_root(self):
        engine = _flat_engine()
        founder = _spawn(engine, 1, 1, 1)
        child = engine.create_child(1)
        grandchild = engine.create_child(child.agent_id)

        chain = engine.ancestors(grandchild.agent_id)

        assert [a.agent_id for a in chain] == [1, 2, 3]
        assert [a.generation for a in chain] == [0, 1, 2]
        assert chain[0] is founder


class TestPopulationMembership:
    def test_spawned_agents_join_the_engine_population(self):
        engine = _flat_engine(population_id=7)
        _spawn(engine, 1, 1, 1)
        _spawn(engine, 2, 1, 2)

        assert {a.agent_id for a in engine.population()} == {1, 2}
        assert engine.population(999) == []

    def test_children_stay_in_the_parent_population(self):
        engine = _flat_engine(population_id=7)
        _spawn(engine, 1, 1, 1)

        child = engine.create_child(1)

        assert child.population_id == 7
        assert {a.agent_id for a in engine.population()} == {1, 2}
