"""S09 — births through the API, lineage in the database.

Registry-created worlds persist a population row and founding agent
rows; the AgentRecorder subscriber persists every birth. The roadmap's
chain is verified here against the database, not just the engine.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import AgentModel, PopulationModel
from app.persistence.repositories import AgentRepository


@pytest.fixture()
def app(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    application = FastAPI()
    application.include_router(health_router, prefix="/api")
    application.include_router(worlds_router, prefix="/api")
    application.state.worlds = WorldRegistry(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    yield application, engine
    asyncio.run(application.state.worlds.stop_all())
    engine.dispose()


@pytest.fixture()
def client(app):
    application, _ = app
    with TestClient(application) as test_client:
        yield test_client


def _create(client, **overrides) -> dict:
    # One founder by default: the second spawns east of the first and
    # can box it in, which is a different test's subject.
    payload = {"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False}
    payload.update(overrides)
    response = client.post("/api/worlds", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestFoundingRows:
    def test_world_creation_writes_population_and_agents(self, client, app):
        _, engine = app
        world = _create(client, agents=2)

        with Session(engine) as session:
            populations = session.query(PopulationModel).all()
            assert len(populations) == 1
            population = populations[0]
            assert population.world_id == world["id"]
            assert population.root_agent_id is not None

            agents = session.query(AgentModel).all()
            assert len(agents) == 2  # the founding generation
            assert all(a.local_id in (1, 2) for a in agents)
            assert all(a.generation == 0 for a in agents)
            assert all(a.parent_id is None for a in agents)
            assert all(a.population_id == population.id for a in agents)
            assert population.root_agent_id == min(a.id for a in agents)


class TestBirths:
    def test_birth_returns_child_and_persists_row(self, client, app):
        _, engine = app
        world = _create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/births",
            json={"parent_id": 1, "inheritance": {"message": "hello"}},
        )
        assert response.status_code == 201
        child = response.json()
        assert child["id"] == 2  # next engine id after the founder
        assert child["parent_id"] == 1
        assert child["generation"] == 1
        assert child["inheritance"] == {
            "traits": {},
            "knowledge": [],
            "message": "hello",
            "cultural_artifacts": [],
        }

        with Session(engine) as session:
            rows = session.query(AgentModel).all()
            assert len(rows) == 2
            child_row = next(r for r in rows if r.local_id == 2)
            parent_row = next(r for r in rows if r.local_id == 1)
            assert child_row.parent_id == parent_row.id  # global ids link
            assert child_row.generation == 1
            assert child_row.birth_tick == 0

    def test_birth_event_on_the_timeline(self, client):
        world = _create(client)
        client.post(f"/api/worlds/{world['id']}/births", json={"parent_id": 1})

        events = client.get(f"/api/worlds/{world['id']}/events?since_id=0").json()["events"]
        born = [e for e in events if e["type"] == "AGENT_BORN"]
        assert len(born) == 1
        assert born[0]["payload"]["parent_id"] == 1
        assert born[0]["payload"]["child_id"] == 2

    def test_unknown_parent_rejected(self, client):
        world = _create(client)
        response = client.post(f"/api/worlds/{world['id']}/births", json={"parent_id": 99})
        assert response.status_code == 400

    def test_no_room_rejected_with_409(self, client):
        # Children fill the four cells adjacent to their parent; the
        # fifth birth has nowhere to go.
        world = _create(client, width=8, height=8, agents=1)
        parent = world["agent_count"]

        status_codes = []
        for _ in range(5):
            response = client.post(
                f"/api/worlds/{world['id']}/births", json={"parent_id": parent}
            )
            status_codes.append(response.status_code)
            if response.status_code == 409:
                break
        assert 409 in status_codes
        assert status_codes.index(409) <= 4

    def test_model_world_child_gets_a_model_policy(self, client):
        world = _create(client, brains="model")
        response = client.post(f"/api/worlds/{world['id']}/births", json={"parent_id": 1})
        assert response.status_code == 201

        client.post(f"/api/worlds/{world['id']}/step")
        events = client.get(f"/api/worlds/{world['id']}/events?since_id=0").json()["events"]
        deciding = {e["actor_id"] for e in events if e["type"] == "MODEL_DECISION"}
        assert deciding == {1, 2}  # founder and the newborn both think (mock provider)


class TestLineageVerification:
    def test_database_chain_matches_the_roadmap_verification(self, client, app):
        # 0 -> 1 -> 2 -> ... -> N, verified against persisted rows.
        _, engine = app
        world = _create(client, width=24, height=24, agents=1)

        parent = 1
        for expected_generation in range(1, 11):
            response = client.post(
                f"/api/worlds/{world['id']}/births", json={"parent_id": parent}
            )
            assert response.status_code == 201
            child = response.json()
            assert child["generation"] == expected_generation
            parent = child["id"]

        repository = AgentRepository(sessionmaker(bind=engine, expire_on_commit=False))
        lineage = repository.lineage(world["id"])
        assert [entry["generation"] for entry in lineage] == list(range(11))
        # Each entry's parent is the previous agent in the chain.
        for entry, previous in zip(lineage[1:], lineage):
            assert entry["parent_local_id"] == previous["local_id"]
        assert lineage[0]["parent_local_id"] is None
