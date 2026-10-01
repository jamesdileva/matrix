"""S06B — Simulation API and live-world hosting.

Each test builds its own FastAPI app bound to a throwaway SQLite file, so
the dev database is never touched and worlds never leak between tests.
"""

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldHost, WorldRegistry
from app.persistence.database import Base
from app.persistence.repositories import EventRepository
from app.simulation.engine import Engine
from app.simulation.world import World


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
    with TestClient(application) as test_client:  # context manager: lifespan runs, portal shuts down
        yield test_client


@pytest.fixture()
def paused_world(client):
    """A created-but-not-ticking world for deterministic assertions."""
    response = client.post(
        "/api/worlds",
        json={"seed": "test", "width": 24, "height": 24, "agents": 2, "autostart": False},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_health_still_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_create_world_returns_full_snapshot(client):
    data = client.post(
        "/api/worlds",
        json={"seed": "snap", "width": 16, "height": 16, "agents": 2, "autostart": False},
    ).json()

    assert data["id"] > 0
    assert data["seed"] == "snap"
    assert data["width"] == 16
    assert data["tick"] == 0
    assert data["paused"] is False
    assert data["agent_count"] == 2
    assert len(data["terrain"]) == 16
    assert len(data["terrain"][0]) == 16
    assert set(data["entities"]) == {"1", "2"}
    assert all("events" not in data for _ in [0])


def test_step_advances_tick_and_state(client, paused_world):
    before = client.get(f"/api/worlds/{paused_world}").json()
    after = client.post(f"/api/worlds/{paused_world}/step").json()

    assert before["tick"] == 0
    assert after["tick"] == 1
    assert after["id"] == paused_world


def test_unknown_world_is_404(client):
    assert client.get("/api/worlds/999").status_code == 404
    assert client.post("/api/worlds/999/step").status_code == 404


def test_pause_and_resume(client, paused_world):
    paused = client.post(f"/api/worlds/{paused_world}/pause").json()
    assert paused == {"id": paused_world, "paused": True}
    assert client.get(f"/api/worlds/{paused_world}").json()["paused"] is True

    resumed = client.post(f"/api/worlds/{paused_world}/resume").json()
    assert resumed["paused"] is False


def test_events_since_id(client, paused_world):
    client.post(f"/api/worlds/{paused_world}/step")
    client.post(f"/api/worlds/{paused_world}/step")

    everything = client.get(f"/api/worlds/{paused_world}/events").json()["events"]
    assert len(everything) > 0
    ids = [e["id"] for e in everything]
    assert ids == sorted(ids)

    cutoff = everything[2]["id"]
    later = client.get(
        f"/api/worlds/{paused_world}/events", params={"since_id": cutoff}
    ).json()["events"]
    assert [e["id"] for e in later] == ids[3:]


def test_delete_stops_and_removes_world(client, paused_world):
    assert client.delete(f"/api/worlds/{paused_world}").json()["stopped"] is True
    assert client.get(f"/api/worlds/{paused_world}").status_code == 404
    listed = client.get("/api/worlds").json()["worlds"]
    assert all(w["id"] != paused_world for w in listed)


def test_autostarted_world_ticks_and_can_be_deleted(client):
    """Covers the autostart path: host.start() needs the event loop, so
    this test would catch a sync-route regression that broke the real
    client (the 500 behind the first E2E attempt)."""
    created = client.post(
        "/api/worlds",
        json={"seed": "live", "width": 16, "height": 16, "agents": 1, "tick_rate": 50.0},
    )
    assert created.status_code == 201
    world_id = created.json()["id"]

    time.sleep(0.3)
    state = client.get(f"/api/worlds/{world_id}").json()
    assert state["tick"] >= 1  # the asyncio loop is ticking it

    assert client.delete(f"/api/worlds/{world_id}").json()["stopped"] is True
    assert client.get(f"/api/worlds/{world_id}").status_code == 404


def test_world_persists_events_to_database(app, client, paused_world):
    """The full chain: API -> engine -> bus -> recorder -> database."""
    _, engine = app
    client.post(f"/api/worlds/{paused_world}/step")
    client.post(f"/api/worlds/{paused_world}/step")

    repo = EventRepository(engine)
    assert repo.count(paused_world) > 0
    rows = repo.recent(paused_world, limit=1000)
    assert rows[0].type == "WORLD_SEEDED"  # the very first event ever
    assert rows[-1].type == "ACTION_EXECUTED"  # the manual step
    assert all(r.sequence is not None for r in rows)


def test_host_max_ticks_run_is_deterministic(app):
    _, engine = app

    def build():
        world = World.generate("host", 12, 12)
        sim_engine = Engine(world)
        host = WorldHost(world_id=1, engine=sim_engine, tps=500)
        return world, host

    world_a, host_a = build()
    world_b, host_b = build()

    async def run_both():
        task_a = host_a.start(max_ticks=10)
        task_b = host_b.start(max_ticks=10)
        await asyncio.gather(task_a, task_b)

    asyncio.run(run_both())

    assert world_a.tick == 10
    assert world_b.tick == 10
    assert world_a.to_dict() == world_b.to_dict()


def test_host_pause_holds_tick(app):
    world = World.generate("pause", 12, 12)
    sim_engine = Engine(world)
    host = WorldHost(world_id=1, engine=sim_engine, tps=500)
    host.paused = True

    async def run():
        task = host.start(max_ticks=10)
        await task

    asyncio.run(run())
    assert world.tick == 0  # paused worlds do not advance
