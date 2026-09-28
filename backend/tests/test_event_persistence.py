"""S05 — event persistence: bus -> recorder -> database -> queries.

The roadmap verification lives here: a scripted sequence whose every
expected event lands in the database, in the correct order, surviving a
process restart (engine disposed, storage reopened).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import Base
from app.persistence.models import WorldModel
from app.persistence.repositories import DatabaseEventRecorder, EventRepository
from app.simulation.bus import EventBus
from app.simulation.world import Position, World


def _make_storage(tmp_path):
    """Own SQLite file + engine so the test can dispose and 'restart'."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'events.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        world_row = WorldModel(name="scripted", seed="script")
        session.add(world_row)
        session.commit()
        world_id = world_row.id
    return engine, world_id


def test_scripted_sequence_persists_every_event_in_order(tmp_path):
    engine, world_id = _make_storage(tmp_path)

    bus = EventBus()
    bus.subscribe(
        DatabaseEventRecorder(
            sessionmaker(bind=engine, expire_on_commit=False), world_id
        )
    )
    world = World.generate("script", 12, 12, event_bus=bus)

    # --- the scripted sequence -----------------------------------------
    world.add_entity(1, Position(2, 2))
    food = world.place_object("food", Position(2, 3))  # south, within reach
    world.execute_action(1, {"action": "look"})
    world.execute_action(1, {"action": "move", "direction": "west"})  # -> (1,2)
    world.execute_action(1, {"action": "move", "direction": "west"})  # border wall
    world.execute_action(1, {"action": "move", "direction": "east"})  # back to (2,2)
    world.execute_action(1, {"action": "pick_up", "object_id": food.id})
    world.execute_action(1, {"action": "pick_up", "object_id": food.id})  # carried
    world.execute_action(1, {"action": "nonsense"})  # unknown
    world.execute_action(1, {"action": "drop", "object_id": food.id})  # at feet
    # --------------------------------------------------------------------

    expected_tail = [
        ("ENTITY_ADDED", 1),
        ("OBJECT_CREATED", None),
        ("ACTION_EXECUTED", 1),  # look
        ("ACTION_EXECUTED", 1),  # move west
        ("ACTION_REJECTED", 1),  # wall
        ("ACTION_EXECUTED", 1),  # move east
        ("ACTION_EXECUTED", 1),  # pick_up
        ("ACTION_REJECTED", 1),  # carried elsewhere
        ("ACTION_REJECTED", 1),  # unknown
        ("ACTION_EXECUTED", 1),  # drop
    ]

    # in-memory timeline: the world's own log matches the expectation
    in_memory = [(e.type, e.actor_id) for e in world.events[-len(expected_tail):]]
    assert in_memory == expected_tail

    # "restart": dispose the engine, reopen the same storage
    engine.dispose()
    reopened = create_engine(
        f"sqlite:///{tmp_path / 'events.db'}",
        connect_args={"check_same_thread": False},
    )
    repo = EventRepository(reopened)

    rows = repo.recent(world_id, limit=1000)
    assert len(rows) == len(world.events)

    # generation prefix: seeded first, then one OBJECT_CREATED per object
    assert rows[0].type == "WORLD_SEEDED"
    generated_creates = [r for r in rows if r.type == "OBJECT_CREATED" and r.actor_id is None]
    assert len(generated_creates) == len(world.objects)

    # the scripted tail lands in the database, in order, with the right actors
    db_tail = [(r.type, r.actor_id) for r in rows[-len(expected_tail):]]
    assert db_tail == expected_tail

    # engine sequence ids and wall-clock metadata are both recorded
    assert [r.sequence for r in rows] == sorted(r.sequence for r in rows)
    assert [r.sequence for r in rows[-len(expected_tail):]] == [
        e.id for e in world.events[-len(expected_tail):]
    ]
    assert all(r.timestamp is not None for r in rows)
    assert all(r.tick == 0 for r in rows)

    # the rejected wall move carries its reason
    wall = [r for r in rows if r.type == "ACTION_REJECTED" and r.payload.get("reason") == "wall"]
    assert len(wall) == 1
    assert wall[0].payload["action"] == {"action": "move", "direction": "west"}

    reopened.dispose()


def test_recent_query_returns_tail_in_order(tmp_path):
    engine, world_id = _make_storage(tmp_path)
    bus = EventBus()
    bus.subscribe(
        DatabaseEventRecorder(sessionmaker(bind=engine, expire_on_commit=False), world_id)
    )
    world = World.generate("tail", 8, 8, event_bus=bus)
    world.add_entity(1, Position(2, 2))
    for _ in range(6):
        world.execute_action(1, {"action": "look"})

    repo = EventRepository(engine)
    tail = repo.recent(world_id, limit=4)
    assert [r.sequence for r in tail] == sorted(r.sequence for r in tail)
    assert [r.type for r in tail] == ["ACTION_EXECUTED"] * 4
    assert tail[0].sequence == len(world.events) - 3


def test_filter_by_type_and_actor(tmp_path):
    engine, world_id = _make_storage(tmp_path)
    bus = EventBus()
    bus.subscribe(
        DatabaseEventRecorder(sessionmaker(bind=engine, expire_on_commit=False), world_id)
    )
    world = World("filter", 12, 12, event_bus=bus)  # plain world: moves below always legal
    world.add_entity(1, Position(2, 2))
    world.add_entity(2, Position(3, 3))
    world.execute_action(1, {"action": "move", "direction": "west"})  # executed, actor 1
    world.execute_action(2, {"action": "move", "direction": "north"})  # executed, actor 2
    world.execute_action(1, {"action": "move", "direction": "east"})  # executed, actor 1
    world.execute_action(1, {"action": "nonsense"})  # rejected, actor 1

    repo = EventRepository(engine)

    rejections = repo.recent(world_id, event_type="ACTION_REJECTED")
    assert [(r.type, r.actor_id) for r in rejections] == [("ACTION_REJECTED", 1)]

    actor2 = repo.recent(world_id, actor_id=2)
    assert [(r.type, r.actor_id) for r in actor2] == [
        ("ENTITY_ADDED", 2),
        ("ACTION_EXECUTED", 2),
    ]

    executed = repo.recent(world_id, event_type="ACTION_EXECUTED")
    assert all(r.type == "ACTION_EXECUTED" for r in executed)
    assert len(executed) == 3


def test_since_id_returns_only_later_events(tmp_path):
    engine, world_id = _make_storage(tmp_path)
    bus = EventBus()
    bus.subscribe(
        DatabaseEventRecorder(sessionmaker(bind=engine, expire_on_commit=False), world_id)
    )
    world = World("since", 8, 8, event_bus=bus)  # plain world: movement always legal
    world.add_entity(1, Position(2, 2))
    for _ in range(5):
        world.execute_action(1, {"action": "look"})

    repo = EventRepository(engine)
    everything = repo.recent(world_id, limit=100)
    cutoff = everything[2].id

    later = repo.recent(world_id, since_id=cutoff)
    assert [r.id for r in later] == [r.id for r in everything[3:]]


def test_recorder_batches_from_multiple_worlds_are_isolated(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'multi.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        a = WorldModel(name="a", seed="a")
        b = WorldModel(name="b", seed="b")
        session.add_all([a, b])
        session.commit()
        a_id, b_id = a.id, b.id

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    bus_a, bus_b = EventBus(), EventBus()
    bus_a.subscribe(DatabaseEventRecorder(session_factory, a_id))
    bus_b.subscribe(DatabaseEventRecorder(session_factory, b_id))

    world_a = World.generate("a", 8, 8, event_bus=bus_a)
    world_b = World.generate("b", 8, 8, event_bus=bus_b)

    repo = EventRepository(engine)
    assert repo.count(a_id) == len(world_a.events)
    assert repo.count(b_id) == len(world_b.events)
    assert repo.recent(a_id)[0].payload["width"] == 8

    engine.dispose()
