"""S18 — building through the API: operator-injected actions and the
structures feed.

Injection travels the same validated path as an agent's own decisions;
the structures route exposes the world's buildings for the console.
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
    payload = {"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False}
    payload.update(overrides)
    response = client.post("/api/worlds", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _act(client, world_id, agent_id, action):
    response = client.post(
        f"/api/worlds/{world_id}/actions",
        json={"agent_id": agent_id, "action": action},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestInjectedActions:
    def test_gather_then_build_a_structure(self, client):
        from app.simulation.world import Position

        world = _create(client)
        host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
        agent_position = host.engine.agents[0].position
        # Clear the founder's neighbours so the test is deterministic,
        # then put a tree east of it: gather wood, build south.
        world_engine = host.engine.world
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = Position(agent_position.x + dx, agent_position.y + dy)
            blocker = world_engine.object_at(cell)
            if blocker is not None:
                world_engine.remove_object(blocker.id)
        tree_cell = Position(agent_position.x + 1, agent_position.y)
        world_engine.place_object("tree", tree_cell, properties={"quantity": 2})

        gathered = _act(client, world["id"], 1, {"action": "gather", "resource": "wood"})
        assert gathered["ok"]
        assert world_engine.resource_count(1, "wood") == 1

        built = _act(
            client,
            world["id"],
            1,
            {"action": "build", "block": "wood_block", "direction": "south",
             "purpose": "shelter"},
        )
        assert built["ok"], built
        assert built["data"]["structure_id"] is not None

        structures = client.get(f"/api/worlds/{world['id']}/structures").json()["structures"]
        assert len(structures) == 1
        assert structures[0]["purpose"] == "shelter"
        assert structures[0]["owner"] == 1
        assert structures[0]["component_count"] == 1
        component = structures[0]["components"][0]
        assert component["type"] == "wood_block"
        assert component["position"] is not None
        assert component["placed_by"] == 1

    def test_rejected_action_is_reported_not_raised(self, client):
        world = _create(client)

        result = _act(client, world["id"], 1, {"action": "gather", "resource": "unobtanium"})

        assert result["ok"] is False
        assert result["reason"] == "unknown_resource"

    def test_unknown_agent_is_404(self, client):
        world = _create(client)
        response = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 99, "action": {"action": "look"}},
        )
        assert response.status_code == 404


class TestStructuresRoute:
    def test_empty_world_has_no_structures(self, client):
        world = _create(client)
        body = client.get(f"/api/worlds/{world['id']}/structures").json()
        assert body == {"world_id": world["id"], "structures": []}

    def test_unknown_world_is_404(self, client):
        assert client.get("/api/worlds/9999/structures").status_code == 404
