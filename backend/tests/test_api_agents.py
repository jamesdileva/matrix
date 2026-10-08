"""S13 — the population feed the Observer Dashboard polls.

`GET /api/worlds/{id}/agents` is what the stats panel reads; the tests
assert the live engine's lineage/status/policy shape the console
renders.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base


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
    payload = {"seed": "matrix", "width": 24, "height": 24, "agents": 2, "autostart": False}
    payload.update(overrides)
    response = client.post("/api/worlds", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestAgentsRoute:
    def test_returns_the_live_population(self, client):
        world = _create(client)

        body = client.get(f"/api/worlds/{world['id']}/agents").json()

        assert body["world_id"] == world["id"]
        assert len(body["agents"]) == 2
        first = body["agents"][0]
        assert first["id"] == 1
        assert first["generation"] == 0
        assert first["parent_id"] is None
        assert first["status"] == "alive"
        assert first["policy"] == "scripted"
        assert first["position"] is not None
        assert first["knowledge"] == 0

    def test_model_world_reports_model_policy(self, client):
        world = _create(client, brains="model")

        body = client.get(f"/api/worlds/{world['id']}/agents").json()

        assert all(agent["policy"] == "model" for agent in body["agents"])

    def test_birth_shows_up_in_the_population_feed(self, client):
        world = _create(client, agents=1)
        client.post(
            f"/api/worlds/{world['id']}/births",
            json={"parent_id": 1, "inheritance": {"knowledge": ["a fact"]}},
        )

        body = client.get(f"/api/worlds/{world['id']}/agents").json()

        child = next(a for a in body["agents"] if a["id"] == 2)
        assert child["generation"] == 1
        assert child["parent_id"] == 1
        assert child["knowledge"] == 1

    def test_unknown_world_is_404(self, client):
        response = client.get("/api/worlds/9999/agents")
        assert response.status_code == 404
