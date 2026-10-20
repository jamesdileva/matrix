"""S44 — Civilization challenges: explicit metrics derived from the world."""

import pytest

from app.simulation.challenges import CHALLENGE_KINDS, Challenge, challenge_catalog
from app.simulation.errors import InvalidPositionError
from app.simulation.games import LONG_ROAD
from app.simulation.geometry import Position
from app.simulation.world import Terrain, World


def bridge_world(seed: str = "bridge") -> World:
    world = World(seed, 10, 5)
    for x in (4, 5, 6):
        world.terrain[2][x] = Terrain.WATER
    world.add_entity(1, Position(3, 2))
    world.credit_resource(1, "wood", 20)
    return world


def settlement_world(seed: str = "village", purpose: str = "home") -> World:
    world = World(seed, 12, 12)
    world.add_entity(1, Position(2, 2))
    world.add_entity(2, Position(2, 3))
    structure_id = world.create_structure(owner=1, purpose=purpose)
    block = world.place_object(
        "wood_block", Position(3, 2), properties={"structure_id": structure_id}
    )
    world.add_to_structure(structure_id, block.id)
    world.found_settlement(1, "Haven", structure_id)
    return world


# --- the shelf ---------------------------------------------------------


def test_catalog_lists_every_kind_with_explicit_metrics():
    catalog = challenge_catalog()
    assert catalog["kinds"] == list(CHALLENGE_KINDS)
    for kind in CHALLENGE_KINDS:
        spec = catalog["challenges"][kind]
        assert spec["name"] and spec["description"] and spec["completion"]
        assert spec["unit"]
        assert "default_target" in spec


# --- bridge ------------------------------------------------------------


def test_bridge_challenge_finds_a_deterministic_span():
    first = bridge_world("same").start_challenge("bridge")
    second = bridge_world("same").start_challenge("bridge")
    assert first.details == second.details
    assert first.target == 3
    assert first.details["axis"] == "horizontal"
    assert [cell["x"] for cell in first.details["cells"]] == [4, 5, 6]
    assert first.details["shores"] == [{"x": 3, "y": 2}, {"x": 7, "y": 2}]


def test_bridge_needs_a_water_span():
    world = World("dry", 10, 5)
    world.add_entity(1, Position(1, 1))
    with pytest.raises(ValueError, match="water span"):
        world.start_challenge("bridge")


def test_wood_can_bridge_water_but_a_door_cannot():
    world = bridge_world("materials")
    assert world.execute_action(
        1, {"action": "build", "block": "wood_block", "direction": "east"}
    ).ok
    assert world.object_at(Position(4, 2)).properties["bridge"] is True
    assert world.execute_action(1, {"action": "move", "direction": "east"}).ok

    with pytest.raises(InvalidPositionError):
        world.place_object("tree", Position(5, 2))

    # The actor stands on the first plank; the next water cell is open.
    result = world.execute_action(
        1, {"action": "build", "block": "door", "direction": "east"}
    )
    assert not result.ok and result.reason == "impassable_terrain"


def test_bridge_planks_are_walkable_and_complete_the_challenge():
    world = bridge_world("crossing")
    challenge = world.start_challenge("bridge")

    for _ in range(3):
        built = world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "east"}
        )
        assert built.ok
        moved = world.execute_action(1, {"action": "move", "direction": "east"})
        assert moved.ok

    assert world.entity_position(1) == Position(6, 2)
    assert challenge.status == "active"
    world.step()
    assert challenge.status == "completed"
    assert challenge.metrics == {"value": 3, "target": 3, "unit": "planks"}
    assert world.object_at(Position(5, 2)).properties["bridge"] is True


def test_standing_on_a_bridge_survives_save_and_restore():
    world = bridge_world("resume-bridge")
    world.start_challenge("bridge")
    for _ in range(2):
        world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "east"}
        )
        world.execute_action(1, {"action": "move", "direction": "east"})
    assert world.entity_position(1) == Position(5, 2)

    data = world.to_dict()
    restored = World.from_dict(data)
    assert restored.entity_position(1) == Position(5, 2)
    assert restored.to_dict() == data
    assert restored.challenge(1).details == world.challenge(1).details


def test_a_bridge_plank_cannot_be_pulled_from_underfoot():
    world = bridge_world("underfoot")
    world.execute_action(
        1, {"action": "build", "block": "wood_block", "direction": "east"}
    )
    # A second walker stands on the first plank while the builder tries
    # to dismantle that very cell.
    world.add_entity(2, Position(4, 2))
    result = world.execute_action(
        1, {"action": "remove", "direction": "east"}
    )
    assert not result.ok and result.reason == "cell_occupied"


# --- settlement and transport -----------------------------------------


def test_settlement_challenge_completes_when_members_arrive():
    world = settlement_world()
    challenge = world.start_challenge("settlement", target=2)
    world.step()
    assert challenge.status == "active"
    assert challenge.metrics["value"] == 1

    settlement = world.settlements[0]
    world.join_settlement(2, settlement.id)
    world.step()
    assert challenge.status == "completed"
    assert challenge.metrics["value"] == 2
    assert challenge.metrics["settlements"] == 1
    assert challenge.metrics["homes"] == 1


def test_transport_counts_storage_above_the_baseline():
    world = settlement_world(seed="stores", purpose="storage")
    settlement = world.settlements[0]
    world.credit_resource(1, "wood", 10)
    world.deposit(1, settlement.id, "wood", 2)

    challenge = world.start_challenge("transport", target=6)
    assert challenge.details["baseline"] == 2
    world.step()
    assert challenge.status == "active"
    assert challenge.metrics["value"] == 0

    world.deposit(1, settlement.id, "wood", 6)
    world.step()
    assert challenge.status == "completed"
    assert challenge.metrics["value"] == 6
    assert challenge.metrics["storage"] == 8


# --- winter ------------------------------------------------------------


def winter_world(seed: str = "winter", season_length: int = 2) -> tuple[World, object]:
    world = World(seed, 8, 8)
    world.add_entity(1, Position(2, 2))
    world.enable_ecosystem(
        season_length=season_length,
        initial_berries=0,
        initial_trees=0,
        initial_grazers=0,
        initial_predators=0,
    )
    return world, world.ecosystem


def test_winter_requires_an_ecosystem():
    world = World("no-sky", 8, 8)
    world.add_entity(1, Position(2, 2))
    with pytest.raises(ValueError, match="ecosystem"):
        world.start_challenge("winter")


def test_winter_completes_when_spring_returns():
    world, _ = winter_world()
    challenge = world.start_challenge("winter")
    assert challenge.details["deadline_tick"] == 8
    assert challenge.details["start_season"] == "spring"

    for _ in range(8):
        world.step()
    assert world.tick == 8
    assert challenge.status == "completed"
    assert challenge.metrics["value"] == 1
    assert challenge.metrics["season"] == "spring"


def test_winter_fails_when_everyone_dies():
    world, _ = winter_world(seed="empty")
    challenge = world.start_challenge("winter")
    world.remove_entity(1)
    world.step()
    assert challenge.status == "failed"
    assert challenge.failed_reason == "no one survived"


def test_winter_fails_with_too_few_survivors():
    world, _ = winter_world(seed="lonely")
    challenge = world.start_challenge("winter", target=2)
    for _ in range(8):
        world.step()
    assert challenge.status == "failed"
    assert "only 1 survived" in challenge.failed_reason


# --- game and discovery ------------------------------------------------


def test_game_challenge_tracks_games_proposed_after_it_begins():
    world = World("play", 8, 8)
    world.add_entity(1, Position(2, 2))
    challenge = world.start_challenge("game")
    world.step()
    assert challenge.status == "active"

    world.propose_game(1, LONG_ROAD)
    world.step()
    assert challenge.status == "completed"
    assert challenge.metrics["value"] == 1


def test_discovery_hides_its_region_until_found():
    world = World("explore", 12, 12)
    world.add_entity(1, Position(1, 1))
    challenge = world.start_challenge("discovery")
    assert challenge.to_dict(reveal=False)["details"] == {"hidden": True}
    assert challenge.details["center"] == {"x": 11, "y": 11}
    assert challenge.details["radius"] == 2

    world.add_entity(2, Position.from_dict(challenge.details["center"]))
    world.step()
    assert challenge.status == "completed"
    revealed = challenge.to_dict(reveal=False)["details"]
    assert revealed["center"] == {"x": 11, "y": 11}
    assert challenge.metrics["distance"] == 0


def test_discovery_needs_an_explorer():
    world = World("nobody", 8, 8)
    with pytest.raises(ValueError, match="someone to explore"):
        world.start_challenge("discovery")


def test_a_discovery_without_a_center_fails_instead_of_crashing():
    world = World("lost", 8, 8)
    world.add_entity(1, Position(1, 1))
    challenge = Challenge.from_dict(
        {"id": 9, "kind": "discovery", "details": {}}
    )
    assert challenge.advance(world) == "failed"
    assert challenge.status == "failed"


# --- lifecycle ---------------------------------------------------------


def test_duplicate_kind_unknown_kind_and_bad_target_are_refused():
    world = settlement_world("rules")
    world.start_challenge("settlement")
    with pytest.raises(ValueError, match="already"):
        world.start_challenge("settlement")
    with pytest.raises(ValueError, match="unknown challenge"):
        world.start_challenge("moonbase")
    with pytest.raises(ValueError, match="positive integer"):
        world.start_challenge("game", target=0)


def test_challenges_ride_the_timeline_and_survive_restore():
    world = settlement_world("timeline")
    world.start_challenge("settlement", target=5)
    world.join_settlement(2, world.settlements[0].id)
    world.step()
    event_types = [event.type for event in world.events]
    assert "CHALLENGE_STARTED" in event_types

    data = world.to_dict()
    restored = World.from_dict(data)
    assert restored.to_dict() == data
    assert [c.to_dict() for c in restored.challenges] == [
        c.to_dict() for c in world.challenges
    ]

    world.step()
    restored.step()
    assert restored.challenge(1).to_dict() == world.challenge(1).to_dict()

    world.start_challenge("game")
    world.propose_game(1, LONG_ROAD)
    world.step()
    assert "CHALLENGE_COMPLETED" in [event.type for event in world.events]
