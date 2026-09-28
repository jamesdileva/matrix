"""S04 — Actions & Rules.

The contract under test: the model proposes, the world decides. Valid
actions succeed and mutate exactly what they claim; invalid actions never
mutate state; every attempt produces exactly one event.
"""

import pytest

from app.simulation.world import Position, Terrain, World


@pytest.fixture()
def world():
    w = World("action-test", 10, 10)
    w.terrain[4][5] = Terrain.WALL  # wall east of (4, 4)  — terrain[y][x]
    w.terrain[5][4] = Terrain.WATER  # water south of (4, 4)
    return w


@pytest.fixture()
def actor_world(world):
    world.add_entity(1, Position(4, 4))
    return world


def _state(world: World) -> dict:
    """World state excluding the event log, which is supposed to grow."""
    data = world.to_dict()
    data.pop("events")
    data.pop("next_event_id")
    return data


# ----------------------------------------------------------------------
# move
# ----------------------------------------------------------------------


def test_valid_move_succeeds(actor_world):
    result = actor_world.execute_action(1, {"action": "move", "direction": "north"})
    assert result.ok is True
    assert result.data["from"] == {"x": 4, "y": 4}
    assert result.data["to"] == {"x": 4, "y": 3}
    assert actor_world.entity_position(1) == Position(4, 3)


def test_wall_collision_fails(actor_world):
    result = actor_world.execute_action(1, {"action": "move", "direction": "east"})
    assert result.ok is False
    assert result.reason == "wall"
    assert actor_world.entity_position(1) == Position(4, 4)


def test_water_blocks_movement(actor_world):
    result = actor_world.execute_action(1, {"action": "move", "direction": "south"})
    assert result.ok is False
    assert result.reason == "water"
    assert actor_world.entity_position(1) == Position(4, 4)


def test_move_out_of_bounds_fails(actor_world):
    actor_world.add_entity(2, Position(0, 1))
    result = actor_world.execute_action(2, {"action": "move", "direction": "west"})
    assert result.ok is False
    assert result.reason == "out_of_bounds"
    assert actor_world.entity_position(2) == Position(0, 1)


def test_move_onto_entity_fails(actor_world):
    actor_world.add_entity(2, Position(4, 3))
    result = actor_world.execute_action(1, {"action": "move", "direction": "north"})
    assert result.ok is False
    assert result.reason == "cell_occupied"
    assert result.data["entity_id"] == 2
    assert actor_world.entity_position(1) == Position(4, 4)


def test_move_onto_object_fails(actor_world):
    actor_world.place_object("stone", Position(3, 4))
    result = actor_world.execute_action(1, {"action": "move", "direction": "west"})
    assert result.ok is False
    assert result.reason == "cell_occupied"
    assert result.data["object_id"] == 1


# ----------------------------------------------------------------------
# look / inspect
# ----------------------------------------------------------------------


def test_look_reports_terrain_objects_and_entities(actor_world):
    actor_world.place_object("tree", Position(4, 3))  # north
    actor_world.add_entity(2, Position(3, 4))  # west
    result = actor_world.execute_action(1, {"action": "look"})
    assert result.ok is True

    cells = {c["direction"]: c for c in result.data["cells"]}
    assert set(cells) == {"here", "north", "south", "east", "west"}
    assert cells["here"]["terrain"] == "floor"
    assert cells["north"]["object"] == {"id": 1, "type": "tree"}
    assert cells["east"]["terrain"] == "wall"
    assert cells["south"]["terrain"] == "water"
    assert cells["west"]["entity"] == 2


def test_inspect_within_reach_returns_details(actor_world):
    obj = actor_world.place_object("food", Position(4, 3))  # north, within reach
    result = actor_world.execute_action(1, {"action": "inspect", "object_id": obj.id})
    assert result.ok is True
    assert result.data["object"]["type"] == "food"
    assert result.data["object"]["position"] == {"x": 4, "y": 3}


def test_inspect_out_of_reach_fails(actor_world):
    obj = actor_world.place_object("food", Position(8, 8))
    result = actor_world.execute_action(1, {"action": "inspect", "object_id": obj.id})
    assert result.ok is False
    assert result.reason == "out_of_reach"


# ----------------------------------------------------------------------
# pick_up / drop / place
# ----------------------------------------------------------------------


def test_pick_up_works(actor_world):
    obj = actor_world.place_object("food", Position(4, 3))  # north, within reach
    result = actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})
    assert result.ok is True
    assert actor_world.object_at(Position(4, 3)) is None
    assert actor_world.inventory(1) == (obj.id,)

    # carried objects serialize with a null position
    assert actor_world.get_object(obj.id).position is None


def test_pick_up_out_of_reach_fails(actor_world):
    obj = actor_world.place_object("food", Position(8, 8))
    result = actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})
    assert result.ok is False
    assert result.reason == "out_of_reach"
    assert actor_world.object_at(Position(8, 8)) is obj
    assert actor_world.inventory(1) == ()


def test_drop_works(actor_world):
    obj = actor_world.place_object("stone", Position(4, 3))
    actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})

    result = actor_world.execute_action(1, {"action": "drop", "object_id": obj.id})
    assert result.ok is True
    assert actor_world.object_at(Position(4, 4)) is obj
    assert actor_world.inventory(1) == ()
    assert actor_world.get_object(obj.id).position == Position(4, 4)


def test_drop_onto_occupied_cell_fails(actor_world):
    """An entity may share its cell with one dropped object, but not two."""
    first = actor_world.place_object("stone", Position(4, 3))  # north
    second = actor_world.place_object("food", Position(3, 4))  # west
    actor_world.execute_action(1, {"action": "pick_up", "object_id": first.id})
    actor_world.execute_action(1, {"action": "pick_up", "object_id": second.id})

    ok = actor_world.execute_action(1, {"action": "drop", "object_id": first.id})
    assert ok.ok is True
    assert actor_world.object_at(Position(4, 4)) is first

    fail = actor_world.execute_action(1, {"action": "drop", "object_id": second.id})
    assert fail.ok is False
    assert fail.reason == "cell_occupied"
    assert actor_world.inventory(1) == (second.id,)


def test_place_onto_occupied_cell_fails(actor_world):
    blocker = actor_world.place_object("stone", Position(4, 3))  # north
    carried = actor_world.place_object("food", Position(3, 4))  # west
    assert actor_world.execute_action(1, {"action": "pick_up", "object_id": carried.id}).ok

    result = actor_world.execute_action(
        1, {"action": "place", "object_id": carried.id, "direction": "north"}
    )
    assert result.ok is False
    assert result.reason == "cell_occupied"
    assert result.data["object_id"] == blocker.id
    assert actor_world.inventory(1) == (carried.id,)  # still carrying
    assert actor_world.object_at(Position(4, 3)) is blocker


def test_place_works(actor_world):
    obj = actor_world.place_object("stone", Position(3, 4))  # west
    actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})

    result = actor_world.execute_action(
        1, {"action": "place", "object_id": obj.id, "direction": "north"}
    )
    assert result.ok is True
    assert actor_world.object_at(Position(4, 3)) is obj
    assert actor_world.inventory(1) == ()


def test_place_requires_direction(actor_world):
    obj = actor_world.place_object("stone", Position(3, 4))
    actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})

    result = actor_world.execute_action(1, {"action": "place", "object_id": obj.id})
    assert result.ok is False
    assert result.reason == "invalid_direction"
    assert actor_world.inventory(1) == (obj.id,)


# ----------------------------------------------------------------------
# Rejection guarantees
# ----------------------------------------------------------------------


def test_invalid_actions_do_not_mutate_state(actor_world):
    before = _state(actor_world)
    bad_actions = [
        {"action": "teleport", "to": [0, 0]},  # unknown action
        {"action": "move"},  # missing direction
        {"action": "move", "direction": "up"},  # bad direction
        {"action": "move", "direction": 7},  # non-string direction
        {"action": "pick_up", "object_id": 999},  # unknown object
        {"action": "pick_up", "object_id": "food"},  # non-integer id
        {"action": "inspect"},  # missing object_id
        "move north",  # not even a dict
        42,  # not a dict
    ]
    for action in bad_actions:
        result = actor_world.execute_action(1, action)
        assert result.ok is False, action
        assert result.reason is not None, action

    assert _state(actor_world) == before


def test_unknown_actor_is_rejected_with_event(world):
    result = world.execute_action(99, {"action": "move", "direction": "north"})
    assert result.ok is False
    assert result.reason == "unknown_actor"
    assert world.events[-1].type == "ACTION_REJECTED"


def test_every_action_creates_exactly_one_event(actor_world):
    start = len(actor_world.events)
    attempts = [
        {"action": "move", "direction": "east"},  # rejected (wall)
        {"action": "move", "direction": "north"},  # executed
        {"action": "look"},  # executed
        {"action": "nonsense"},  # rejected (unknown)
    ]
    for action in attempts:
        actor_world.execute_action(1, action)

    events = actor_world.events
    assert len(events) == start + len(attempts)
    assert [e.type for e in events[start:]] == [
        "ACTION_REJECTED",
        "ACTION_EXECUTED",
        "ACTION_EXECUTED",
        "ACTION_REJECTED",
    ]
    ids = [e.id for e in events]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert all(e.tick == 0 for e in events)


def test_action_state_serialization_round_trip(actor_world):
    obj = actor_world.place_object("food", Position(4, 3))  # north
    actor_world.execute_action(1, {"action": "pick_up", "object_id": obj.id})
    actor_world.execute_action(1, {"action": "move", "direction": "east"})  # wall -> rejected
    actor_world.execute_action(1, {"action": "move", "direction": "north"})  # executed

    data = actor_world.to_dict()
    restored = World.from_dict(data)

    assert restored.to_dict() == data
    assert restored.entity_position(1) == Position(4, 3)
    assert restored.inventory(1) == (obj.id,)
    assert actor_world.get_object(obj.id).position is None
    assert [e.type for e in restored.events] == [
        "ACTION_EXECUTED",  # pick_up
        "ACTION_REJECTED",  # move east into wall
        "ACTION_EXECUTED",  # move north
    ]

    # restored world keeps working: the carried object can be dropped
    result = restored.execute_action(1, {"action": "drop", "object_id": obj.id})
    assert result.ok is True
    assert restored.object_at(Position(4, 3)) is not None
