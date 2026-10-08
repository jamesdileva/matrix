"""S08 — model worlds over the Simulation API.

`brains: "model"` is an explicit opt-in; the default provider chain is
the offline mock, so these tests create real model worlds with no
network. Decision events must persist through the recorder and be
queryable through the events API like any other event.
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
from app.persistence.repositories import EventRepository
from app.simulation.events import EventTypes


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


class TestBrainsOptIn:
    def test_scripted_is_the_default(self, client):
        response = client.post("/api/worlds", json={"seed": "s", "autostart": False})
        assert response.status_code == 201
        assert response.json()["brains"] == "scripted"
        assert response.json()["provider"] is None

    def test_model_world_reports_its_provider(self, client):
        response = client.post(
            "/api/worlds", json={"seed": "s", "autostart": False, "brains": "model"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["brains"] == "model"
        # Default provider chain (FLOOD_MODEL_PROVIDER=mock).
        assert body["provider"] == {"provider": "mock", "model": "mock-1"}

    def test_unknown_brains_rejected(self, client):
        response = client.post(
            "/api/worlds", json={"seed": "s", "autostart": False, "brains": "telepathy"}
        )
        assert response.status_code == 400

    def test_model_world_listed_with_brains(self, client):
        created = client.post(
            "/api/worlds", json={"seed": "s", "autostart": False, "brains": "model"}
        ).json()
        listed = client.get("/api/worlds").json()["worlds"]
        entry = next(w for w in listed if w["id"] == created["id"])
        assert entry["brains"] == "model"


class TestModelWorldRuns:
    def test_manual_step_records_decision_events(self, client, app):
        created = client.post(
            "/api/worlds",
            json={
                "seed": "matrix",
                "width": 24,
                "height": 24,
                "agents": 2,
                "autostart": False,
                "brains": "model",
            },
        )
        world_id = created.json()["id"]

        response = client.post(f"/api/worlds/{world_id}/step")
        assert response.status_code == 200
        assert response.json()["tick"] == 1

        events = client.get(f"/api/worlds/{world_id}/events?since_id=0&limit=50").json()["events"]
        decisions = [e for e in events if e["type"] == EventTypes.MODEL_DECISION]
        assert len(decisions) == 2  # one per model agent
        assert all(d["payload"]["provider"] == "mock" for d in decisions)
        assert all(d["payload"]["outcome"]["ok"] for d in decisions)

    def test_decisions_persist_through_the_recorder(self, client, app):
        _, engine = app
        created = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1,
                  "autostart": False, "brains": "model"},
        )
        world_id = created.json()["id"]
        client.post(f"/api/worlds/{world_id}/step")

        repository = EventRepository(engine)
        rows = repository.recent(world_id, limit=10, event_type=EventTypes.MODEL_DECISION)
        assert len(rows) == 1
        assert rows[0].type == EventTypes.MODEL_DECISION

    def test_autostarted_model_world_ticks_and_stops_clean(self, client):
        created = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1,
                  "tick_rate": 30.0, "brains": "model"},
        )
        world_id = created.json()["id"]

        import time

        deadline = time.time() + 10
        while time.time() < deadline:
            body = client.get(f"/api/worlds/{world_id}").json()
            if body["tick"] >= 2:
                break
            time.sleep(0.1)
        assert body["tick"] >= 2

        response = client.delete(f"/api/worlds/{world_id}")
        assert response.status_code == 200
