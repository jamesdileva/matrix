from app.persistence.models import World


def test_database_initializes_from_empty_state(db_session):
    assert db_session.query(World).count() == 0


def test_world_insert_and_retrieve(db_session):
    world = World(
        name="void-0",
        seed="seed-42",
        dimensions={"width": 64, "height": 64},
        ruleset={"movement": "grid4"},
    )
    db_session.add(world)
    db_session.commit()

    fetched = db_session.query(World).one()
    assert fetched.id is not None
    assert fetched.name == "void-0"
    assert fetched.seed == "seed-42"
    assert fetched.tick == 0
    assert fetched.dimensions == {"width": 64, "height": 64}
    assert fetched.ruleset == {"movement": "grid4"}


def test_world_tick_persists_on_update(db_session):
    world = World(name="void-1", seed="s")
    db_session.add(world)
    db_session.commit()

    world.tick = 128
    db_session.commit()

    fetched = db_session.query(World).one()
    assert fetched.tick == 128
