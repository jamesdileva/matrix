import json

import pytest

from app.simulation.errors import CellOccupiedError, InvalidPositionError
from app.simulation.world import Position, Terrain, World


def test_same_seed_produces_identical_worlds():
    a = World.generate("matrix", 24, 24)
    b = World.generate("matrix", 24, 24)
    assert a.to_dict() == b.to_dict()


def test_different_seeds_produce_different_worlds():
    a = World.generate("matrix", 24, 24)
    b = World.generate("other", 24, 24)
    assert a.to_dict() != b.to_dict()


def test_world_shape_and_solid_border():
    world = World.generate("matrix", 16, 12)
    assert world.width == 16
    assert world.height == 12
    for x in range(16):
        assert world.terrain_at(Position(x, 0)) is Terrain.WALL
        assert world.terrain_at(Position(x, 11)) is Terrain.WALL
    for y in range(12):
        assert world.terrain_at(Position(0, y)) is Terrain.WALL
        assert world.terrain_at(Position(15, y)) is Terrain.WALL


def test_tick_advances():
    world = World.generate("matrix", 8, 8)
    assert world.tick == 0
    assert world.step() == 1
    assert world.step() == 2
    assert world.tick == 2


def test_generated_objects_sit_on_valid_floor_cells():
    world = World.generate("matrix", 24, 24)
    assert len(world.objects) > 0
    ids = []
    for obj in world.objects:
        assert world.in_bounds(obj.position)
        assert world.terrain_at(obj.position) is Terrain.FLOOR
        assert world.object_at(obj.position) is obj
        ids.append(obj.id)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_place_object_on_floor():
    world = World("t", 8, 8)
    pos = Position(3, 4)
    obj = world.place_object("tree", pos, properties={"age": 2})
    assert obj.id == 1
    assert obj.type == "tree"
    assert obj.position == pos
    assert obj.created_tick == 0
    assert world.object_at(pos) is obj
    assert world.get_object(1) is obj

    second = world.place_object("stone", Position(5, 5))
    assert second.id == 2


def test_place_object_rejects_out_of_bounds():
    world = World("t", 8, 8)
    for pos in [Position(-1, 3), Position(8, 3), Position(3, -1), Position(3, 8)]:
        with pytest.raises(InvalidPositionError):
            world.place_object("tree", pos)


def test_place_object_rejects_wall_and_water():
    world = World("t", 8, 8)
    world.terrain[2][4] = Terrain.WALL
    world.terrain[5][2] = Terrain.WATER
    with pytest.raises(InvalidPositionError):
        world.place_object("tree", Position(4, 2))
    with pytest.raises(InvalidPositionError):
        world.place_object("tree", Position(2, 5))


def test_place_object_rejects_occupied_cell():
    world = World("t", 8, 8)
    world.place_object("tree", Position(3, 3))
    with pytest.raises(CellOccupiedError):
        world.place_object("stone", Position(3, 3))


def test_place_object_rejects_non_integer_coordinates():
    world = World("t", 8, 8)
    with pytest.raises(InvalidPositionError):
        world.place_object("tree", Position(1.5, 3))
    with pytest.raises(InvalidPositionError):
        world.place_object("tree", Position(True, 3))


def test_serialization_round_trip_preserves_everything():
    world = World.generate("matrix", 24, 24)
    for _ in range(5):
        world.step()
    world.place_object("food", Position(1, 1), properties={"fresh": True}, created_by_agent_id=7)

    data = world.to_dict()
    restored = World.from_dict(data)

    assert restored.to_dict() == data
    assert restored.tick == 5
    assert restored.seed == "matrix"
    food = restored.object_at(Position(1, 1))
    assert food is not None
    assert food.properties == {"fresh": True}
    assert food.created_by_agent_id == 7


def test_serialized_world_is_json_safe():
    world = World.generate("matrix", 16, 16)
    assert json.loads(json.dumps(world.to_dict())) == world.to_dict()


def test_restored_world_continues_object_id_sequence():
    world = World.generate("matrix", 16, 16)
    original_count = len(world.objects)
    data = world.to_dict()
    restored = World.from_dict(data)

    obj = restored.place_object("tree", Position(2, 2))
    assert obj.id == data["next_object_id"]
    assert len(restored.objects) == original_count + 1


def test_render_is_full_grid_with_solid_border():
    world = World.generate("matrix", 10, 8)
    lines = world.render().splitlines()
    assert len(lines) == 8
    assert all(len(line) == 10 for line in lines)
    assert set(lines[0]) == {"#"}
    assert set(lines[-1]) == {"#"}
