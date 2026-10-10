"""S20 — the human avatar: a participant entity in a live world.

The roadmap's check is "observer can enter Participant Mode and move
around without stopping the simulation" — so these tests assert the
entity appears, moves under the same rules as agents, is visible to
them, and leaves the tick loop undisturbed.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import PARTICIPANT_ENTITY_ID, WorldRegistry
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


class TestParticipation:
    def test_join_places_an_entity_in_the_world(self, client):
        world = _create(client)

        joined = client.post(f"/api/worlds/{world['id']}/participant/join").json()

        assert joined["joined"] is True
        assert joined["entity_id"] == PARTICIPANT_ENTITY_ID
        assert joined["position"] is not None
        # The state snapshot shows the participant among the entities.
        state = client.get(f"/api/worlds/{world['id']}").json()
        assert str(PARTICIPANT_ENTITY_ID) in state["entities"]

    def test_not_joined_reports_none(self, client):
        world = _create(client)
        body = client.get(f"/api/worlds/{world['id']}/participant").json()
        assert body["participant"] is None

    def test_join_is_idempotent(self, client):
        world = _create(client)
        first = client.post(f"/api/worlds/{world['id']}/participant/join").json()
        second = client.post(f"/api/worlds/{world['id']}/participant/join").json()
        assert first["position"] == second["position"]
        assert second["joined"] is False

    def test_leave_removes_the_entity(self, client):
        world = _create(client)
        client.post(f"/api/worlds/{world['id']}/participant/join")

        left = client.post(f"/api/worlds/{world['id']}/participant/leave").json()

        assert left["left"] is True
        state = client.get(f"/api/worlds/{world['id']}").json()
        assert str(PARTICIPANT_ENTITY_ID) not in state["entities"]
        assert client.get(f"/api/worlds/{world['id']}/participant").json()["participant"] is None

    def test_move_follows_the_worlds_rules(self, client):
        world = _create(client)
        joined = client.post(f"/api/worlds/{world['id']}/participant/join").json()

        # Walk the first legal direction out of the spawn cell (the
        # participant starts in a corner, so not every way is open).
        moved = None
        for direction in ("east", "south", "north", "west"):
            candidate = client.post(
                f"/api/worlds/{world['id']}/participant/move", json={"direction": direction}
            ).json()
            if candidate["ok"]:
                moved = candidate
                break
        assert moved is not None
        assert moved["position"] != joined["position"]
        bad = client.post(
            f"/api/worlds/{world['id']}/participant/move", json={"direction": "sideways"}
        ).json()
        assert bad["ok"] is False

    def test_move_without_joining_is_rejected(self, client):
        world = _create(client)
        response = client.post(
            f"/api/worlds/{world['id']}/participant/move", json={"direction": "north"}
        )
        assert response.status_code == 409

    def test_participant_does_not_stop_the_simulation(self, client):
        world = _create(client, autostart=True, tick_rate=30.0)
        client.post(f"/api/worlds/{world['id']}/participant/join")

        import time

        time.sleep(1.0)
        tick_with = client.get(f"/api/worlds/{world['id']}").json()["tick"]
        client.post(f"/api/worlds/{world['id']}/participant/leave")

        assert tick_with > 0  # the world kept ticking with the avatar in it

    def test_agents_see_the_participant(self, client):
        world = _create(client, agents=1, autostart=False)
        joined = client.post(f"/api/worlds/{world['id']}/participant/join").json()
        host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]

        # Put the participant next to the founder so the observation shows it.
        from app.simulation.world import Position

        agent = host.engine.agents[0]
        spot = Position(joined["position"]["x"], joined["position"]["y"])
        host.engine.world.remove_entity(PARTICIPANT_ENTITY_ID)
        host.engine.world.add_entity(
            PARTICIPANT_ENTITY_ID,
            Position(spot.x, spot.y + 1)
            if host.engine.world.is_floor(Position(spot.x, spot.y + 1))
            else spot,
        )
        observation = agent.observe()
        seen = [c.get("entity") for c in observation["cells"]] + [
            n.get("id") for n in observation["nearby"] if n.get("kind") == "entity"
        ]
        assert PARTICIPANT_ENTITY_ID in seen

    def test_unknown_world_is_404(self, client):
        assert client.get("/api/worlds/9999/participant").status_code == 404
        assert client.post("/api/worlds/9999/participant/join").status_code == 404
