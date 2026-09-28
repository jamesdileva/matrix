from app.persistence.models import AgentModel, PopulationModel, WorldModel


def _world(db_session) -> WorldModel:
    world = WorldModel(name="void-0", seed="seed-42")
    db_session.add(world)
    db_session.commit()
    return world


def test_agent_insert_and_retrieve(db_session):
    world = _world(db_session)

    agent = AgentModel(
        world_id=world.id,
        location={"x": 10, "y": 4},
        inherited_knowledge={"facts": ["water is drinkable"]},
    )
    db_session.add(agent)
    db_session.commit()

    fetched = db_session.query(AgentModel).one()
    assert fetched.world_id == world.id
    assert fetched.generation == 0
    assert fetched.status == "active"
    assert fetched.location == {"x": 10, "y": 4}
    assert fetched.inherited_knowledge == {"facts": ["water is drinkable"]}


def test_agent_parent_id_and_generation(db_session):
    world = _world(db_session)

    parent = AgentModel(world_id=world.id, generation=0)
    db_session.add(parent)
    db_session.flush()  # real engine: the parent exists before the child is created

    child = AgentModel(world_id=world.id, parent_id=parent.id, generation=1)
    db_session.add(child)
    db_session.commit()

    fetched_child = db_session.query(AgentModel).filter_by(generation=1).one()
    assert fetched_child.parent_id == parent.id
    assert fetched_child.parent is parent
    assert [c.id for c in fetched_child.parent.children] == [fetched_child.id]


def test_agent_population_membership(db_session):
    world = _world(db_session)

    population = PopulationModel(
        name="founders",
        world_id=world.id,
        model_configuration={"provider": "mock"},
    )
    db_session.add(population)
    db_session.commit()

    agent = AgentModel(world_id=world.id, population_id=population.id, generation=0)
    db_session.add(agent)
    db_session.commit()

    fetched = db_session.query(PopulationModel).one()
    assert [a.id for a in fetched.agents] == [agent.id]
    assert agent.population.model_configuration == {"provider": "mock"}
