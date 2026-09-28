"""S05 — event model, bus, and world event emission (in-memory side)."""

from app.simulation.bus import EventBus
from app.simulation.events import Event, EventTypes
from app.simulation.world import Position, World


def test_event_bus_delivers_in_order_to_all_subscribers():
    bus = EventBus()
    first, second = [], []
    bus.subscribe(first.append)
    bus.subscribe(second.append)

    world = World.generate("bus", 8, 8, event_bus=bus)
    world.add_entity(1, Position(2, 2))
    world.execute_action(1, {"action": "move", "direction": "north"})
    world.execute_action(1, {"action": "move", "direction": "north"})

    assert [e.to_dict() for e in first] == [e.to_dict() for e in world.events]
    assert [e.id for e in second] == [e.id for e in first]
    assert len(first) > 0


def test_generate_and_entities_emit_the_expected_world_events():
    world = World.generate("types", 8, 8)
    types = [e.type for e in world.events]

    assert types[0] == EventTypes.WORLD_SEEDED
    assert types.count(EventTypes.OBJECT_CREATED) == len(world.objects)
    assert EventTypes.OBJECT_CREATED in types

    spot = next(
        Position(x, y)
        for y in range(1, world.height - 1)
        for x in range(1, world.width - 1)
        if world.is_floor(Position(x, y)) and world.object_at(Position(x, y)) is None
    )
    world.add_entity(1, spot)
    assert world.events[-1].type == EventTypes.ENTITY_ADDED
    assert world.events[-1].payload == {"position": spot.to_dict()}

    world.remove_entity(1)
    assert world.events[-1].type == EventTypes.ENTITY_REMOVED


def test_object_created_event_carries_actor_and_target():
    world = World("t", 8, 8)
    obj = world.place_object("stone", Position(3, 3), created_by_agent_id=7)

    event = world.events[-1]
    assert event.type == EventTypes.OBJECT_CREATED
    assert event.actor_id == 7
    assert event.target_id == obj.id
    assert event.payload == {
        "type": "stone",
        "position": {"x": 3, "y": 3},
        "created_tick": 0,
    }


def test_action_event_payload_carries_action_and_reason():
    world = World("t", 8, 8)
    world.add_entity(1, Position(2, 2))

    ok = world.execute_action(1, {"action": "move", "direction": "north"})
    assert ok.event.type == EventTypes.ACTION_EXECUTED
    assert ok.event.payload["action"] == {"action": "move", "direction": "north"}
    assert ok.event.payload["to"] == {"x": 2, "y": 1}

    bad = world.execute_action(1, {"action": "move", "direction": "up"})
    assert bad.event.type == EventTypes.ACTION_REJECTED
    assert bad.event.payload["reason"] == "invalid_direction"


def test_events_are_part_of_deterministic_state():
    a = World.generate("same", 12, 12)
    b = World.generate("same", 12, 12)
    assert [e.to_dict() for e in a.events] == [e.to_dict() for e in b.events]

    c = World.generate("other", 12, 12)
    assert [e.to_dict() for e in a.events] != [e.to_dict() for e in c.events]


def test_world_without_bus_still_records_events():
    world = World("t", 8, 8)
    world.place_object("tree", Position(1, 1))
    assert world.events[-1].type == EventTypes.OBJECT_CREATED


def test_event_ids_are_sequential_across_all_event_kinds():
    world = World.generate("seq", 8, 8)
    world.add_entity(1, Position(2, 2))
    world.execute_action(1, {"action": "look"})

    ids = [e.id for e in world.events]
    assert ids == list(range(1, len(ids) + 1))
