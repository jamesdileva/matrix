"""S44 — Challenge API: catalog, start, live metrics, and verdicts."""

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
from app.simulation.geometry import Position


@pytest.fixture()
def app(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'challenges.db'}",
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


def create(client, *, ecosystem: bool = False, agents: int = 2) -> dict:
    response = client.post(
        "/api/worlds",
        json={
            "seed": "challenge-api",
            "width": 16,
            "height": 16,
            "agents": agents,
            "autostart": False,
            "ecosystem": ecosystem,
        },
    )
    assert response.status_code == 201
    return response.json()


def start(client, world_id: int, kind: str, **payload) -> dict:
    response = client.post(
        f"/api/worlds/{world_id}/challenges",
        json={"kind": kind, **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge"]


def test_the_challenge_shelf_is_public(client):
    catalog = client.get("/api/challenges").json()
    assert catalog["kinds"] == [
        "bridge", "settlement", "transport", "winter", "game", "discovery",
    ]
    for kind in catalog["kinds"]:
        assert catalog["challenges"][kind]["completion"]
        assert catalog["challenges"][kind]["unit"]


def test_start_list_detail_and_refusals(client):
    world = create(client)
    challenge = start(client, world["id"], "settlement", target=2, name="Our Home")
    assert challenge["name"] == "Our Home"
    assert challenge["status"] == "active"
    assert challenge["metrics"] == {"value": 0, "target": 2, "unit": "members"}

    listed = client.get(f"/api/worlds/{world['id']}/challenges").json()
    assert [item["id"] for item in listed["challenges"]] == [challenge["id"]]

    detail = client.get(
        f"/api/worlds/{world['id']}/challenges/{challenge['id']}"
    ).json()["challenge"]
    assert detail["kind"] == "settlement"

    duplicate = client.post(
        f"/api/worlds/{world['id']}/challenges", json={"kind": "settlement"}
    )
    assert duplicate.status_code == 400

    unknown = client.post(
        f"/api/worlds/{world['id']}/challenges", json={"kind": "moonbase"}
    )
    assert unknown.status_code == 400

    assert client.post("/api/worlds/9999/challenges", json={"kind": "game"}).status_code == 404
    missing = client.get(f"/api/worlds/{world['id']}/challenges/999")
    assert missing.status_code == 404


def test_winter_requires_an_ecosystem_and_then_completes(client):
    plain = create(client)
    refused = client.post(
        f"/api/worlds/{plain['id']}/challenges", json={"kind": "winter"}
    )
    assert refused.status_code == 400
    assert "ecosystem" in refused.json()["detail"]

    living = create(client, ecosystem=True, agents=1)
    host = client.app.state.worlds.get(living["id"])  # type: ignore[attr-defined]
    host.engine.world.ecosystem.season_length = 2
    challenge = start(client, living["id"], "winter")

    for _ in range(8):
        assert client.post(f"/api/worlds/{living['id']}/step").status_code == 200

    detail = client.get(
        f"/api/worlds/{living['id']}/challenges/{challenge['id']}"
    ).json()["challenge"]
    assert detail["status"] == "completed"
    assert detail["metrics"]["value"] == 1
    assert detail["metrics"]["season"] == "spring"


def test_discovery_hides_its_region_until_an_entity_arrives(client):
    world = create(client, agents=2)
    challenge = start(client, world["id"], "discovery")
    assert challenge["details"] == {"hidden": True}

    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    center = challenge["details"].get("center")
    assert center is None
    hidden_center = host.engine.world.challenge(challenge["id"]).details["center"]
    host.engine.world.add_entity(99, Position.from_dict(hidden_center))

    assert client.post(f"/api/worlds/{world['id']}/step").status_code == 200
    detail = client.get(
        f"/api/worlds/{world['id']}/challenges/{challenge['id']}"
    ).json()["challenge"]
    assert detail["status"] == "completed"
    assert detail["details"]["center"] == hidden_center
