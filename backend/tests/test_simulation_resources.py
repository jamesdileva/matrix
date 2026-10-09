"""S17 — resources: quantities, gathering, depletion, and the
conservation invariant the roadmap asks for.

"Agents can gather resources and resource quantities remain
consistent" — so beyond the action's happy path, these tests hold the
world's total resource count (object quantities + entity ledgers)
fixed across gathers, and check depletion removes sources exactly once.
"""

import pytest

from app.simulation.actions import execute_action
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import GathererPolicy, WanderPolicy
from app.simulation.world import Position, Terrain, World


def _flat_world(size: int = 9) -> World:
    return World(
        "t",
        size,
        size,
        terrain=[[Terrain.FLOOR] * size for _ in range(size)],
    )


def _with_source(kind: str, quantity: int = 3, *, actor_position=(4, 4), water_to=None):
    """A world with one source of `kind` adjacent to the actor's cell."""
    world = _flat_world()
    if kind == "water":
        terrain = [row[:] for row in world.terrain]
        terrain[actor_position[1] - 1][actor_position[0]] = Terrain.WATER
        world = World("t2", 9, 9, terrain=terrain)
        source_type = "water"
    else:
        source_type = {"wood": "tree", "stone": "stone", "food": "food"}[kind]
        world.place_object(source_type, Position(actor_position[0], actor_position[1] - 1),
                           properties={"quantity": quantity})
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(*actor_position))
    return engine, source_type


class TestGeneration:
    def test_generated_objects_carry_quantities(self):
        world = World.generate("matrix", 24, 24)
        assert world.objects
        for obj in world.objects:
            assert obj.properties["quantity"] > 0
            assert obj.properties["quantity"] == {"tree": 3, "stone": 3, "food": 2}[obj.type]

    def test_quantities_are_deterministic(self):
        first = World.generate("matrix", 24, 24)
        second = World.generate("matrix", 24, 24)
        assert [(o.type, o.position, o.properties) for o in first.objects] == [
            (o.type, o.position, o.properties) for o in second.objects
        ]

    def test_snapshot_and_observation_expose_quantities(self):
        world = World.generate("matrix", 24, 24)
        snapshot = world.snapshot()
        assert all("quantity" in obj for obj in snapshot["objects"])

        engine = Engine(world)
        obj = world.objects[0]
        spot = next(
            Position(obj.position.x + dx, obj.position.y + dy)
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
            if world.is_floor(Position(obj.position.x + dx, obj.position.y + dy))
            and world.object_at(Position(obj.position.x + dx, obj.position.y + dy)) is None
        )
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), spot)
        observation = engine.agents[0].observe()
        assert observation["resources"] == {}
        quantities = [
            n.get("quantity") for n in observation["nearby"] if n.get("kind") == "object"
        ]
        assert any(q for q in quantities)


class TestGather:
    def test_gather_wood_from_adjacent_tree(self):
        engine, _ = _with_source("wood", quantity=3)

        result = engine.world.execute_action(1, {"action": "gather", "resource": "wood"})

        assert result.ok
        assert engine.world.resource_count(1, "wood") == 1
        tree = next(o for o in engine.world.objects if o.type == "tree")
        assert tree.properties["quantity"] == 2

    def test_gather_water_from_adjacent_water(self):
        engine, _ = _with_source("water")

        result = engine.world.execute_action(1, {"action": "gather", "resource": "water"})

        assert result.ok
        assert engine.world.resource_count(1, "water") == 1

    def test_depletion_removes_the_source_once(self):
        engine, _ = _with_source("wood", quantity=1)

        first = engine.world.execute_action(1, {"action": "gather", "resource": "wood"})
        second = engine.world.execute_action(1, {"action": "gather", "resource": "wood"})

        assert first.ok and first.data["depleted"] is True
        assert engine.world.resource_count(1, "wood") == 1
        assert not [o for o in engine.world.objects if o.type == "tree"]
        depleted = [e for e in engine.world.events if e.type == EventTypes.OBJECT_DEPLETED]
        assert len(depleted) == 1
        assert depleted[0].target_id is not None
        # The second attempt finds nothing and is rejected, not crashed.
        assert not second.ok
        assert second.reason == "no_source_nearby"
        assert engine.world.resource_count(1, "wood") == 1

    def test_rejections(self):
        engine, _ = _with_source("stone", quantity=2)  # a stone source, not a tree

        no_tree = engine.world.execute_action(1, {"action": "gather", "resource": "wood"})
        unknown = engine.world.execute_action(1, {"action": "gather", "resource": "unobtanium"})
        missing_kind = engine.world.execute_action(1, {"action": "gather"})

        assert not no_tree.ok and no_tree.reason == "no_source_nearby"
        assert not unknown.ok and unknown.reason == "unknown_resource"
        assert not missing_kind.ok and missing_kind.reason == "unknown_resource"
        assert engine.world.resources(1) == {}

    def test_conservation_across_gathers(self):
        engine, _ = _with_source("wood", quantity=3)

        before = engine.world.total_resources()
        for _ in range(3):
            engine.world.execute_action(1, {"action": "gather", "resource": "wood"})
        after = engine.world.total_resources()

        assert before["wood"] == 3
        assert after["wood"] == 3  # every unit moved; nothing created or lost
        assert engine.world.resource_count(1, "wood") == 3

    def test_conservation_with_multiple_actors(self):
        engine, _ = _with_source("wood", quantity=3)
        engine.spawn_agent(Agent(agent_id=2, policy=WanderPolicy()), Position(4, 2))  # north of the tree

        before = engine.world.total_resources()
        engine.world.execute_action(1, {"action": "gather", "resource": "wood"})
        engine.world.execute_action(2, {"action": "gather", "resource": "wood"})
        after = engine.world.total_resources()

        assert before["wood"] == after["wood"] == 3
        assert engine.world.resource_count(1, "wood") == 1
        assert engine.world.resource_count(2, "wood") == 1


class TestGathererPolicy:
    def test_gathers_wood_in_a_live_world(self):
        world = World.generate("woodland", 24, 24)
        engine = Engine(world)
        # Place the agent next to a tree.
        tree = next((o for o in world.objects if o.type == "tree"), None)
        assert tree is not None, "seeded world has no tree"
        adjacent = [
            Position(tree.position.x + dx, tree.position.y + dy)
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
        ]
        spot = next(p for p in adjacent if world.is_floor(p) and world.object_at(p) is None)
        engine.spawn_agent(Agent(agent_id=1, policy=GathererPolicy("wood")), spot)

        engine.run(6)

        assert engine.world.resource_count(1, "wood") >= 1

    def test_walks_to_water_and_gathers(self):
        # A dry island in a water ring: the gatherer must step to water.
        size = 15
        terrain = [[Terrain.FLOOR] * size for _ in range(size)]
        for x in range(size):
            terrain[0][x] = Terrain.WATER
        world = World("island", size, size, terrain=terrain)
        engine = Engine(world)
        engine.spawn_agent(Agent(agent_id=1, policy=GathererPolicy("water")), Position(7, 7))

        engine.run(20)

        assert engine.world.resource_count(1, "water") >= 1

    def test_unknown_resource_rejected(self):
        with pytest.raises(ValueError, match="unknown resource"):
            GathererPolicy("unobtanium")
