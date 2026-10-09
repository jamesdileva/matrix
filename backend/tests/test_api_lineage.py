"""S15 — the lineage explorer's feed: ancestry with drift.

The roadmap's check is "select Agent 100 and navigate to Agent 0 and
intermediate generations" — so these tests build a small chain, walk
it from the deepest agent, and assert each member's state and drift
against the founder's knowledge.
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


FACTS = ["the void is dark", "water blocks the walker", "walls stop movement"]


def _chain(client, world_id, *, parent, transports):
    """Continue a chain from `parent`, each generation passing the next
    transport package. Returns the deepest agent's id."""
    for transport in transports:
        response = client.post(
            f"/api/worlds/{world_id}/births",
            json={"parent_id": parent, "inheritance": transport},
        )
        assert response.status_code == 201, response.text
        parent = response.json()["id"]
    return parent


def _lineage(client, world_id, agent_id):
    response = client.get(f"/api/worlds/{world_id}/agents/{agent_id}/lineage")
    assert response.status_code == 200, response.text
    return response.json()


class TestLineageExplorer:
    def test_chain_from_deepest_agent_to_founder(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 32, "height": 32, "agents": 1, "autostart": False},
        ).json()
        # The founder carries the controlled set; each child passes it on.
        child = client.post(
            f"/api/worlds/{world['id']}/births",
            json={"parent_id": 1, "inheritance": {"knowledge": FACTS}},
        ).json()["id"]
        deepest = _chain(
            client,
            world["id"],
            parent=child,
            transports=[
                {"knowledge": FACTS, "message": "second"},
                {"knowledge": FACTS[:2], "message": "third"},
            ],
        )
        assert deepest == 4

        lineage = _lineage(client, world["id"], deepest)

        assert [m["generation"] for m in lineage["chain"]] == [0, 1, 2, 3]
        assert [m["id"] for m in lineage["chain"]] == [1, 2, 3, 4]
        # Navigation links: each member knows its parent.
        assert [m["parent_id"] for m in lineage["chain"]] == [None, 1, 2, 3]
        # Children, where the world has any.
        assert lineage["chain"][0]["children"] == [2]
        assert lineage["chain"][-1]["children"] == []

        # Drift is measured against the lineage's originals — here the
        # set generation 1 received (the founder itself started empty).
        first_carrier = lineage["chain"][1]["drift"]
        assert first_carrier["retained"] == sorted(FACTS)
        assert first_carrier["avg_similarity"] == 1.0
        deepest_drift = lineage["chain"][-1]["drift"]
        assert deepest_drift["lost"] == ["walls stop movement"]

    def test_founder_lineage_is_itself(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()

        lineage = _lineage(client, world["id"], 1)

        assert len(lineage["chain"]) == 1
        assert lineage["chain"][0]["generation"] == 0
        assert lineage["chain"][0]["parent_id"] is None

    def test_drift_against_the_lineage_originals(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 32, "height": 32, "agents": 1, "autostart": False},
        ).json()
        child = client.post(
            f"/api/worlds/{world['id']}/births",
            json={"parent_id": 1, "inheritance": {"knowledge": FACTS}},
        ).json()["id"]
        # Generation 2 drops one fact and invents another.
        _chain(
            client,
            world["id"],
            parent=child,
            transports=[{"knowledge": FACTS[:2] + ["the echo hums"]}],
        )

        lineage = _lineage(client, world["id"], 3)

        # The originals are the earliest carrier's set; the founder
        # itself started empty, and its drift row says so.
        founder_drift = lineage["chain"][0]["drift"]
        assert founder_drift["retained"] == []
        assert founder_drift["lost"] == sorted(FACTS)
        assert lineage["chain"][1]["drift"]["retained"] == sorted(FACTS)

        deepest = lineage["chain"][-1]["drift"]
        assert sorted(deepest["retained"]) == sorted(FACTS[:2])
        assert deepest["lost"] == ["walls stop movement"]
        assert deepest["new"] == ["the echo hums"]

    def test_drift_uses_the_founder_as_originals(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        # Founder itself knows nothing; the controlled set arrives with
        # the first child — that set is this lineage's originals.
        _chain(client, world["id"], parent=1, transports=[{"knowledge": FACTS}])
        lineage = _lineage(client, world["id"], 2)

        assert lineage["chain"][0]["knowledge"] == []  # the founder's own
        assert lineage["chain"][0]["drift"]["retained"] == []
        assert lineage["chain"][1]["drift"]["retained"] == sorted(FACTS)

    def test_inheritance_messages_are_the_first_recollection(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 32, "height": 32, "agents": 1, "autostart": False},
        ).json()
        _chain(client, world["id"], parent=1, transports=[{"knowledge": FACTS, "message": "first light"}])

        lineage = _lineage(client, world["id"], 2)

        assert lineage["chain"][1]["inheritance_message"] == "first light"
        assert lineage["chain"][0]["inheritance_message"] is None

    def test_unknown_agent_is_404(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        response = client.get(f"/api/worlds/{world['id']}/agents/99/lineage")
        assert response.status_code == 404

    def test_unknown_world_is_404(self, client):
        response = client.get("/api/worlds/9999/agents/1/lineage")
        assert response.status_code == 404
