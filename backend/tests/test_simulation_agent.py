"""S06 — Scripted Agent: the first inhabitant.

Every roadmap checklist item is here: spawns, moves, observes, interacts
with an object, and every event identifies its actor — plus engine
determinism and a long-run survival check.
"""

import pytest

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import (
    AlwaysMoveNorthPolicy,
    ForagerPolicy,
    WanderPolicy,
)
from app.simulation.world import Position, Terrain, World


@pytest.fixture()
def world():
    return World("agent-test", 12, 12)  # all-floor; obstacles placed per test


def test_agent_spawns_into_world(world):
    agent = Agent(agent_id=1, policy=WanderPolicy())
    agent.spawn(world, Position(3, 3))

    assert agent.status == "alive"
    assert agent.position == Position(3, 3)
    assert world.entity_position(1) == Position(3, 3)
    assert world.events[-1].type == EventTypes.ENTITY_ADDED
    assert world.events[-1].actor_id == 1


def test_agent_cannot_spawn_twice(world):
    agent = Agent(agent_id=1, policy=WanderPolicy())
    agent.spawn(world, Position(3, 3))
    with pytest.raises(RuntimeError):
        agent.spawn(world, Position(4, 4))


def test_observe_before_spawn_raises(world):
    agent = Agent(agent_id=1, policy=WanderPolicy())
    with pytest.raises(RuntimeError):
        agent.observe()


def test_agent_observes_bounded_neighbourhood(world):
    world.terrain[1][5] = Terrain.WALL  # wall at (5,1), directly north of (5,2); terrain[y][x]
    agent = Agent(agent_id=1, policy=WanderPolicy(), observation_radius=2)
    agent.spawn(world, Position(5, 2))
    food = world.place_object("food", Position(6, 2))  # distance 1
    far = world.place_object("stone", Position(9, 2))  # distance 4: outside radius

    obs = agent.observe()

    assert obs["self"] == {
        "id": 1,
        "position": {"x": 5, "y": 2},
        "tick": 0,
        "goal": None,
    }
    directions = [c["direction"] for c in obs["cells"]]
    assert directions == ["here", "north", "south", "east", "west"]
    north_cell = next(c for c in obs["cells"] if c["direction"] == "north")
    assert north_cell["terrain"] == "wall"

    nearby_objects = [n for n in obs["nearby"] if n["kind"] == "object"]
    assert [n["id"] for n in nearby_objects] == [food.id]  # far stone excluded
    assert nearby_objects[0]["distance"] == 1
    assert obs["inventory"] == []
    assert obs["messages"] == []


def test_agent_moves_via_policy_and_events_name_the_actor(world):
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=7, policy=AlwaysMoveNorthPolicy()), Position(5, 5))

    (result,) = engine.step()

    assert result.ok is True
    assert result.actor_id == 7
    assert agent_position(engine, 7) == Position(5, 4)
    move_events = [e for e in world.events if e.type == EventTypes.ACTION_EXECUTED]
    assert [e.actor_id for e in move_events] == [7]
    assert move_events[0].tick == 1  # world stepped first


def agent_position(engine: Engine, agent_id: int) -> Position:
    return engine.world.entity_position(agent_id)


def test_agent_interacts_with_object_via_forager(world):
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=1, policy=ForagerPolicy()), Position(5, 5))
    food = world.place_object("food", Position(5, 4))  # adjacent, north

    (result,) = engine.step()

    assert result.ok is True
    assert world.inventory(1) == (food.id,)
    assert world.object_at(Position(5, 4)) is None
    assert world.get_object(food.id).position is None  # carried


def test_forager_walks_toward_visible_food(world):
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=1, policy=ForagerPolicy()), Position(5, 5))
    food = world.place_object("food", Position(7, 5))  # two cells east, within radius 2

    engine.step()  # sees it, walks east to (6,5)
    assert agent_position(engine, 1) == Position(6, 5)
    engine.step()  # food adjacent -> picks it up

    assert world.inventory(1) == (food.id,)


def test_malformed_decision_is_rejected_not_fatal(world):
    class BrokenPolicy:
        def decide(self, observation):
            return {"nonsense": True}

    engine = Engine(world)
    agent = Agent(agent_id=1, policy=BrokenPolicy())
    engine.spawn_agent(agent, Position(5, 5))

    (result,) = engine.step()
    assert result.ok is False
    assert result.reason == "invalid_action"
    assert agent.status == "alive"  # survives its broken mind
    assert agent.position == Position(5, 5)  # unmoved


def test_events_identify_the_correct_agent(world):
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=1, policy=AlwaysMoveNorthPolicy()), Position(5, 5))
    engine.spawn_agent(Agent(agent_id=2, policy=ForagerPolicy()), Position(8, 8))
    world.place_object("food", Position(8, 7))  # for agent 2 to grab

    start = len(world.events)
    engine.step()

    new_events = world.events[start:]
    actors = {e.actor_id for e in new_events if e.type.startswith("ACTION_")}
    assert actors == {1, 2}

    # each actor's events are attributable and independent
    agent1_events = [e for e in new_events if e.actor_id == 1]
    assert [e.type for e in agent1_events] == [EventTypes.ACTION_EXECUTED]
    # agent 1 (move north) is at (5,4); agent 2 picked up its food
    assert agent_position(engine, 1) == Position(5, 4)
    assert len(world.inventory(2)) == 1
    assert agent_position(engine, 2) == Position(8, 8)


def test_engine_is_deterministic():
    def build():
        w = World.generate("determinism", 16, 16)
        engine = Engine(w)
        spots = [
            Position(x, y)
            for y in range(1, w.height - 1)
            for x in range(1, w.width - 1)
            if w.is_floor(Position(x, y)) and w.object_at(Position(x, y)) is None
        ][:3]
        policies = [WanderPolicy(), ForagerPolicy(), WanderPolicy(("west", "south", "east", "north"))]
        for i, (spot, policy) in enumerate(zip(spots, policies), start=1):
            engine.spawn_agent(Agent(agent_id=i, policy=policy), spot)
        return engine

    a, b = build(), build()
    a.run(25)
    b.run(25)

    assert a.world.to_dict() == b.world.to_dict()


def test_agent_survives_hundreds_of_ticks():
    world = World.generate("survival", 20, 20)
    engine = Engine(world)
    spots = [
        Position(x, y)
        for y in range(1, world.height - 1)
        for x in range(1, world.width - 1)
        if world.is_floor(Position(x, y)) and world.object_at(Position(x, y)) is None
    ][:2]
    engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), spots[0])
    engine.spawn_agent(Agent(agent_id=2, policy=ForagerPolicy()), spots[1])

    for _ in range(300):
        engine.step()

    assert world.tick == 300
    for agent in engine.agents:
        assert agent.status == "alive"
        pos = agent.position
        assert world.is_floor(pos) or world.object_at(pos) is not None  # valid spot

    # every recorded event belongs to a known actor (or a world event)
    known_actors = {1, 2, None}
    assert all(e.actor_id in known_actors for e in world.events)
