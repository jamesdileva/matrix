from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.persistence.database import Base
from app.persistence.models import Event, World


def test_event_insert_and_query_by_world_and_tick(db_session):
    world = World(name="void-0", seed="seed-42")
    db_session.add(world)
    db_session.commit()

    db_session.add_all(
        [
            Event(
                world_id=world.id,
                tick=7,
                type="AGENT_BORN",
                actor_id=None,
                payload={"generation": 0},
            ),
            Event(
                world_id=world.id,
                tick=9,
                type="ACTION_ATTEMPTED",
                actor_id=1,
                target_id=2,
                payload={"action": "move", "direction": "north"},
            ),
        ]
    )
    db_session.commit()

    born = db_session.query(Event).filter_by(type="AGENT_BORN").one()
    assert born.tick == 7
    assert born.payload == {"generation": 0}
    assert db_session.query(Event).filter_by(world_id=world.id).count() == 2


def test_events_persist_after_process_restart(tmp_path):
    """Dispose and reopen the engine — the closest thing to a process
    restart without spawning a subprocess. Events must survive."""
    db_path = tmp_path / "restart.db"
    url = f"sqlite:///{db_path}"

    first_engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(first_engine)
    first_session = sessionmaker(bind=first_engine, expire_on_commit=False)()
    world = World(name="void-0", seed="seed-42")
    first_session.add(world)
    first_session.commit()
    first_session.add(
        Event(world_id=world.id, tick=7, type="AGENT_BORN", payload={})
    )
    first_session.commit()
    first_session.close()
    first_engine.dispose()

    second_engine = create_engine(url, connect_args={"check_same_thread": False})
    second_session = sessionmaker(bind=second_engine, expire_on_commit=False)()

    assert second_session.query(World).count() == 1
    event = second_session.query(Event).one()
    assert event.type == "AGENT_BORN"
    assert event.tick == 7

    second_session.close()
    second_engine.dispose()
