"""S18 — building: blocks cost materials, occupy cells, and group into
structures.

The roadmap's check is "a scripted agent can construct a valid
structure" — plus the invariants that keep buildings honest: material
conservation (a block is spent ledger in object form), validation
before anything half-applies, and grouping that follows contiguity.
"""

import pytest

import pytest

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import BuilderPolicy, GathererPolicy, WanderPolicy
from app.simulation.world import Position, Terrain, World


def _flat_world(size: int = 9) -> World:
    return World(
        "t",
        size,
        size,
        terrain=[[Terrain.FLOOR] * size for _ in range(size)],
    )


def _builder(wood: int = 5, stone: int = 0, *, position=(4, 4)) -> Engine:
    world = _flat_world()
    engine = Engine(world)
    engine.spawn_agent(Agent(agent_id=1, policy=BuilderPolicy()), Position(*position))
    if wood:
        world.credit_resource(1, "wood", wood)
    if stone:
        world.credit_resource(1, "stone", stone)
    return engine


class TestBuild:
    def test_placing_a_block_spends_material_and_occupies(self):
        engine = _builder(wood=3)

        result = engine.world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "north"}
        )

        assert result.ok
        assert engine.world.resource_count(1, "wood") == 2
        block = engine.world.object_at(Position(4, 3))
        assert block is not None and block.type == "wood_block"
        assert block.properties["placed_by"] == 1
        # A wall is a wall: moving onto it is refused.
        move = engine.world.execute_action(1, {"action": "move", "direction": "north"})
        assert not move.ok
        assert move.reason == "cell_occupied"

    def test_insufficient_materials_rejected(self):
        engine = _builder(wood=0)

        result = engine.world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "north"}
        )

        assert not result.ok
        assert result.reason == "insufficient_materials"
        assert engine.world.object_at(Position(4, 3)) is None
        assert engine.world.resources(1) == {}

    def test_unknown_block_rejected(self):
        engine = _builder(wood=3)
        result = engine.world.execute_action(
            1, {"action": "build", "block": "gold_block", "direction": "north"}
        )
        assert not result.ok and result.reason == "unknown_block"

    def test_occupied_and_impassable_rejected(self):
        engine = _builder(wood=3)
        engine.world.place_object("stone", Position(4, 3), properties={"quantity": 1})
        occupied = engine.world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "north"}
        )
        assert not occupied.ok and occupied.reason == "cell_occupied"

        # An impassable target (a wall to the west of a second agent).
        engine.world.terrain[1][0] = Terrain.WALL
        engine.spawn_agent(Agent(agent_id=2, policy=WanderPolicy()), Position(1, 1))
        engine.world.credit_resource(2, "wood", 1)
        wall = engine.world.execute_action(
            2, {"action": "build", "block": "wood_block", "direction": "west"}
        )
        assert not wall.ok and wall.reason == "impassable_terrain"

    def test_stone_blocks_cost_stone(self):
        engine = _builder(wood=0, stone=2)

        result = engine.world.execute_action(
            1, {"action": "build", "block": "stone_block", "direction": "north"}
        )

        assert result.ok
        assert engine.world.resource_count(1, "stone") == 1
        assert engine.world.resource_count(1, "wood") == 0


class TestStructures:
    def test_adjacent_blocks_group_into_one_structure(self):
        # Two blocks placed from one cell are diagonal to each other —
        # contiguity comes from walking the worksite, like the builder.
        engine = _builder(wood=2)

        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})
        engine.world.execute_action(1, {"action": "move", "direction": "east"})
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})

        structures = engine.world.structures()
        assert len(structures) == 1
        assert len(structures[0].components) == 2
        assert structures[0].owner == 1
        created = [e for e in engine.world.events if e.type == EventTypes.STRUCTURE_CREATED]
        assert len(created) == 1

    def test_separate_blocks_stay_separate_structures(self):
        engine = _builder(wood=2)
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})
        engine.world.remove_block(
            next(o.id for o in engine.world.objects if o.type == "wood_block")
        )
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "south"})

        structures = engine.world.structures()
        # The first structure dissolved when its only block was removed;
        # the new block starts a fresh one.
        assert len(structures) == 1
        assert engine.world.object_at(Position(4, 5)) is not None
        assert engine.world.object_at(Position(4, 3)) is None

    def test_explicit_structure_id_joins_across_gaps(self):
        engine = _builder(wood=3)
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})
        structure_id = engine.world.structures()[0].id

        # A block far away, explicitly joining the first structure.
        result = engine.world.execute_action(
            1,
            {"action": "build", "block": "wood_block", "direction": "south",
             "structure": structure_id, "purpose": "house"},
        )

        assert result.ok
        assert result.data["structure_id"] == structure_id
        assert len(engine.world.structures()) == 1
        assert engine.world.structure_by_id(structure_id).purpose == "house"

    def test_unknown_structure_rejected(self):
        engine = _builder(wood=3)
        result = engine.world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "north", "structure": 99}
        )
        assert not result.ok and result.reason == "unknown_structure"

    def test_remove_refunds_and_frees_the_cell(self):
        engine = _builder(wood=1)
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})

        result = engine.world.execute_action(1, {"action": "remove", "direction": "north"})

        assert result.ok
        assert result.data["refunded"] == {"wood": 1}
        assert engine.world.resource_count(1, "wood") == 1
        assert engine.world.object_at(Position(4, 3)) is None
        assert engine.world.structures() == []  # the emptied structure is gone
        # And the cell is buildable/walkable again.
        walk = engine.world.execute_action(1, {"action": "move", "direction": "north"})
        assert walk.ok

    def test_remove_rejects_non_blocks(self):
        engine = _builder(wood=3)
        result = engine.world.execute_action(1, {"action": "remove", "direction": "north"})
        assert not result.ok and result.reason == "not_a_block"


class TestConservation:
    def test_building_moves_material_without_creating_it(self):
        engine = _builder(wood=3, stone=2)

        def total() -> dict:
            ledger = dict(engine.world.resources(1))
            blocks: dict[str, int] = {}
            for obj in engine.world.objects:
                material = obj.properties.get("material") or {}
                for kind, amount in material.items():
                    blocks[kind] = blocks.get(kind, 0) + amount
            return {**ledger, **{f"block_{k}": v for k, v in blocks.items()}}

        before = total()
        engine.world.execute_action(1, {"action": "build", "block": "wood_block", "direction": "north"})
        engine.world.execute_action(1, {"action": "build", "block": "stone_block", "direction": "east"})
        after = total()

        assert before == {"wood": 3, "stone": 2}
        assert after == {"wood": 2, "stone": 1, "block_wood": 1, "block_stone": 1}


class TestScriptedConstruction:
    def test_builder_constructs_a_valid_structure(self):
        # The roadmap's check: a scripted agent constructs a valid
        # structure from materials it was granted.
        engine = _builder(wood=5)
        builder = engine.agents[0]

        engine.run(12)

        structures = engine.world.structures()
        assert len(structures) == 1
        structure = structures[0]
        assert len(structure.components) >= 3  # a wall, not a stumble
        assert structure.owner == builder.agent_id
        # Every component is a block, and all stand on the grid.
        components = [engine.world.get_object(i) for i in structure.components]
        assert all(o is not None and o.type == "wood_block" for o in components)
        assert all(o.position is not None for o in components)
        # The structure is contiguous: every block touches another.
        positions = {o.position for o in components}
        touches = all(
            any(
                abs(o.position.x - p.x) + abs(o.position.y - p.y) == 1
                for p in positions
                if p != o.position
            )
            for o in components
        )
        assert touches
        # The builder's wood went into the world, not nowhere.
        assert engine.world.resource_count(1, "wood") == 5 - len(structure.components)

    def test_builder_stops_when_materials_run_out(self):
        engine = _builder(wood=2)

        engine.run(20)

        blocks = [o for o in engine.world.objects if o.type == "wood_block"]
        assert len(blocks) == 2
        assert engine.world.resource_count(1, "wood") == 0


class TestDecisionContract:
    def test_build_through_the_agent_lifecycle(self):
        # The build action arrives like any other decision, and the
        # memory records the outcome.
        engine = _builder(wood=1)

        engine.step()

        assert engine.agents[0].memory.recent()[-1]["action"]["action"] == "build"
        assert engine.world.structures()[0].owner == 1
