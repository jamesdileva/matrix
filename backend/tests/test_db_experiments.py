from app.persistence.models import ExperimentModel, WorldModel


def test_experiment_insert_and_retrieve(db_session):
    world = WorldModel(name="void-0", seed="seed-42")
    db_session.add(world)
    db_session.commit()

    experiment = ExperimentModel(
        name="lineage-drift-1",
        world_id=world.id,
        scenario="lineage_drift",
        seed="seed-42",
        model_configuration={"provider": "mock"},
        compute_budget={"max_model_calls": 100, "max_tokens": 10000},
        generation_limit=100,
    )
    db_session.add(experiment)
    db_session.commit()

    fetched = db_session.query(ExperimentModel).one()
    assert fetched.name == "lineage-drift-1"
    assert fetched.status == "created"
    assert fetched.scenario == "lineage_drift"
    assert fetched.compute_budget == {"max_model_calls": 100, "max_tokens": 10000}
    assert fetched.generation_limit == 100
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.world.seed == "seed-42"
