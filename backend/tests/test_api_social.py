"""S22 — social interaction through the API: the participant trades,
gives, takes and gathers a group.

The roadmap's check is the headline test: a human trades an object
with an agent and the resulting inventory/world state is exactly
what the timeline says it is.
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
from app.simulation.world import Position


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


def _world_with_agent(client) -> dict:
    response = client.post(
        "/api/worlds",
        json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
    )
    assert response.status_code == 201, response.text
    world = response.json()
    client.post(f"/api/worlds/{world['id']}/participant/join")
    return world


def _host(client, world_id):
    return client.app.state.worlds.get(world_id)  # type: ignore[attr-defined]


def _clear_neighbours(world, position) -> None:
    """Empty the four cells around `position` for deterministic placement."""
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        cell = Position(position.x + dx, position.y + dy)
        blocker = world.object_at(cell)
        if blocker is not None:
            world.remove_object(blocker.id)


def _pick_up_via_api(client, world_id, actor_id, object_id):
    result = client.post(
        f"/api/worlds/{world_id}/actions",
        json={"agent_id": actor_id, "action": {"action": "pick_up", "object_id": object_id}},
    ).json()
    assert result["ok"], result
    return result


class TestTrade:
    def test_human_trades_an_object_with_an_agent(self, client):
        world = _world_with_agent(client)
        host = _host(client, world["id"])
        world_engine = host.engine.world
        agent_position = host.engine.agents[0].position
        _clear_neighbours(world_engine, agent_position)

        # The participant picks up a stone; the agent holds a food.
        stone = world_engine.place_object(
            "stone", Position(agent_position.x + 1, agent_position.y), properties={"quantity": 1}
        )
        _pick_up_via_api(client, world["id"], PARTICIPANT_ENTITY_ID, stone.id)
        food = world_engine.place_object(
            "food", Position(agent_position.x, agent_position.y + 1), properties={"quantity": 1}
        )
        _pick_up_via_api(client, world["id"], 1, food.id)

        traded = client.post(
            f"/api/worlds/{world['id']}/trade",
            json={
                "agent_id": 1,
                "give": {"object_id": stone.id},
                "want": {"object_id": food.id},
            },
        ).json()

        assert traded["ok"] is True
        # The resulting inventories are exactly what the timeline says.
        assert world_engine.inventory(PARTICIPANT_ENTITY_ID) == (food.id,)
        assert world_engine.inventory(1) == (stone.id,)
        transfers = [e for e in world_engine.events if e.type == "TRANSFER"]
        assert len(transfers) == 2  # both legs recorded
        assert all(t.payload["kind"] == "trade" for t in transfers)

    def test_a_trade_the_agent_cannot_back_fails_atomically(self, client):
        world = _world_with_agent(client)
        host = _host(client, world["id"])
        world_engine = host.engine.world
        agent_position = host.engine.agents[0].position
        _clear_neighbours(world_engine, agent_position)
        stone = world_engine.place_object(
            "stone", Position(agent_position.x + 1, agent_position.y), properties={"quantity": 1}
        )
        _pick_up_via_api(client, world["id"], PARTICIPANT_ENTITY_ID, stone.id)

        response = client.post(
            f"/api/worlds/{world['id']}/trade",
            json={"agent_id": 1, "give": {"object_id": stone.id},
                  "want": {"object_id": 4242}},
        )

        assert response.status_code == 400
        assert world_engine.inventory(PARTICIPANT_ENTITY_ID) == (stone.id,)

    def test_trade_requires_proximity(self, client):
        world = _world_with_agent(client)
        host = _host(client, world["id"])
        # Move the participant far from the agent.
        agent_position = host.engine.agents[0].position
        host.engine.world.remove_entity(PARTICIPANT_ENTITY_ID)
        host.engine.world.add_entity(
            PARTICIPANT_ENTITY_ID, Position(agent_position.x + 10, agent_position.y)
        )
        response = client.post(
            f"/api/worlds/{world['id']}/trade",
            json={"agent_id": 1, "give": {"object_id": 1}, "want": {"object_id": 1}},
        )
        assert response.status_code == 400


class TestGiveAndTake:
    def test_give_a_resource_to_an_agent(self, client):
        world = _world_with_agent(client)
        host = _host(client, world["id"])
        host.engine.world.credit_resource(PARTICIPANT_ENTITY_ID, "wood", 2)

        given = client.post(
            f"/api/worlds/{world['id']}/give",
            json={"agent_id": 1, "leg": {"resource": "wood", "amount": 1}},
        ).json()

        assert given["ok"] is True
        assert host.engine.world.resource_count(1, "wood") == 1
        assert host.engine.world.resource_count(PARTICIPANT_ENTITY_ID, "wood") == 1

    def test_take_a_resource_back(self, client):
        world = _world_with_agent(client)
        host = _host(client, world["id"])
        host.engine.world.credit_resource(1, "stone", 2)

        taken = client.post(
            f"/api/worlds/{world['id']}/take",
            json={"agent_id": 1, "leg": {"resource": "stone", "amount": 1}},
        ).json()

        assert taken["ok"] is True
        assert host.engine.world.resource_count(1, "stone") == 1
        assert host.engine.world.resource_count(PARTICIPANT_ENTITY_ID, "stone") == 1

    def test_give_without_joining_is_rejected(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        response = client.post(
            f"/api/worlds/{world['id']}/give",
            json={"agent_id": 1, "leg": {"object_id": 1}},
        )
        assert response.status_code == 409


class TestGroup:
    def test_group_follow_gathers_nearby_agents(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 3, "autostart": False},
        ).json()
        client.post(f"/api/worlds/{world['id']}/participant/join")
        host = _host(client, world["id"])

        # Only the agents within the radius join; sweep a wide net.
        gathered = client.post(
            f"/api/worlds/{world['id']}/group",
            json={"radius": 200, "following": True},
        ).json()

        assert gathered["following"] is True
        assert set(gathered["agents"]) == {1, 2, 3}
        for agent_id in (1, 2, 3):
            assert host.engine.world.follow_target(agent_id) == PARTICIPANT_ENTITY_ID

        # And they scatter again.
        scattered = client.post(
            f"/api/worlds/{world['id']}/group",
            json={"radius": 200, "following": False},
        ).json()
        assert set(scattered["agents"]) == {1, 2, 3}
        for agent_id in (1, 2, 3):
            assert host.engine.world.follow_target(agent_id) is None

    def test_group_follow_moves_the_group(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 2, "autostart": True,
                  "tick_rate": 30.0},
        ).json()
        client.post(f"/api/worlds/{world['id']}/participant/join")
        host = _host(client, world["id"])
        client.post(
            f"/api/worlds/{world['id']}/group", json={"radius": 200, "following": True}
        )

        import time

        participant_position = host.engine.world.entity_position(PARTICIPANT_ENTITY_ID)

        def _max_distance() -> int:
            best = 0
            for agent in host.engine.agents:
                if not host.engine.world.follow_target(agent.agent_id):
                    continue
                best = max(
                    best,
                    abs(agent.position.x - participant_position.x)
                    + abs(agent.position.y - participant_position.y),
                )
            return best

        before = _max_distance()
        time.sleep(0.5)
        after = _max_distance()
        # Followers close in and hold — they never wander off.
        assert after <= before
        assert after <= 1 or before - after > 0, "the group should hold together"
