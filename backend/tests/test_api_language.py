"""S42 — Language API: speak, learn, and inspect a world's repertoires."""

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
        f"sqlite:///{tmp_path / 'language.db'}",
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


@pytest.fixture()
def paused_world(client):
    response = client.post(
        "/api/worlds",
        json={"seed": "language-api", "width": 12, "height": 12,
              "agents": 2, "autostart": False},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_speak_learn_and_summary(client, paused_world):
    spoken = client.post(
        f"/api/worlds/{paused_world}/language/speak",
        json={"speaker_id": 1, "message": "water stone"},
    )
    assert spoken.status_code == 200
    body = spoken.json()
    assert body["text"] == "water stone"
    assert body["message"] != "water stone"
    assert set(body["symbols"]) == {"water", "stone"}

    learned = client.post(
        f"/api/worlds/{paused_world}/language/learn",
        json={"listener_id": 2, "speaker_id": 1},
    )
    assert learned.status_code == 200
    assert {change["concept"] for change in learned.json()["learned"]} == {
        "water", "stone",
    }

    summary = client.get(f"/api/worlds/{paused_world}/language").json()
    assert summary["agreement"] == 1.0
    assert {item["concept"] for item in summary["shared_words"]} == {
        "water", "stone",
    }
    assert summary["changes"] >= 4


def test_speak_via_the_action_route(client, paused_world):
    response = client.post(
        f"/api/worlds/{paused_world}/actions",
        json={"agent_id": 1, "action": {"action": "speak", "message": "tree"}},
    )
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["text"] == "tree"
    assert body["data"]["message"] != "tree"


def test_unknown_agents_are_404(client, paused_world):
    assert client.post(
        f"/api/worlds/{paused_world}/language/speak",
        json={"speaker_id": 99, "message": "water"},
    ).status_code == 404
    assert client.post(
        f"/api/worlds/{paused_world}/language/learn",
        json={"listener_id": 99, "speaker_id": 1},
    ).status_code == 404


def test_empty_message_is_rejected(client, paused_world):
    direct = client.post(
        f"/api/worlds/{paused_world}/language/speak",
        json={"speaker_id": 1, "message": "  "},
    )
    assert direct.status_code == 400

    response = client.post(
        f"/api/worlds/{paused_world}/actions",
        json={"agent_id": 1, "action": {"action": "speak", "message": "  "}},
    )
    assert response.json()["ok"] is False
    assert response.json()["reason"] == "empty_message"
