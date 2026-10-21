"""S45 — Human intervention API: apply, measure, and inspect effects."""

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
from app.simulation.geometry import Position
from app.simulation.interventions import INTERVENTION_KINDS


@pytest.fixture()
def app(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'interventions.db'}",
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


def create(client, *, populations=None, agents: int = 2) -> dict:
    payload = {
        "seed": "intervention-api",
        "width": 16,
        "height": 16,
        "agents": agents,
        "autostart": False,
    }
    if populations is not None:
        payload["populations"] = populations
    response = client.post("/api/worlds", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def intervene(client, world_id: int, **payload) -> dict:
    response = client.post(
        f"/api/worlds/{world_id}/interventions", json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_intervention_shelf_is_public(client):
    catalog = client.get("/api/interventions").json()
    assert [item["kind"] for item in catalog["kinds"]] == list(INTERVENTION_KINDS)
    assert "knowledge_facts" in catalog["metrics"]


def test_provide_information_changes_knowledge_and_is_measured(client):
    world = create(client, agents=1)
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    agent_id = host.engine.agents[0].agent_id

    result = intervene(
        client,
        world["id"],
        kind="provide_information",
        agent_id=agent_id,
        facts=["fire is hot", "recipe:door"],
    )

    assert result["new_facts"] == ["fire is hot", "recipe:door"]
    assert result["technology"] == ["recipe:door"]
    assert result["intervention"]["delta"]["knowledge_facts"] == 2
    assert "fire is hot" in host.engine.agents[0].knowledge
    assert host.engine.world.known_recipes(agent_id) == ["door"]

    detail = client.get(
        f"/api/worlds/{world['id']}/interventions/{result['intervention']['id']}"
    ).json()["intervention"]
    assert detail["baseline"]["knowledge_facts"] == 0
    assert detail["current"]["knowledge_facts"] == 2

    again = intervene(
        client,
        world["id"],
        kind="provide_information",
        agent_id=agent_id,
        facts=["fire is hot"],
    )
    assert again["new_facts"] == []


def test_remove_information_takes_facts_and_technology(client):
    world = create(client, agents=1)
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    agent_id = host.engine.agents[0].agent_id
    intervene(
        client,
        world["id"],
        kind="provide_information",
        agent_id=agent_id,
        facts=["fire is hot", "recipe:door"],
    )

    result = intervene(
        client,
        world["id"],
        kind="remove_information",
        agent_id=agent_id,
        facts=["fire is hot", "recipe:door"],
    )

    assert result["removed"] == ["fire is hot", "recipe:door"]
    assert result["revoked_technology"] == ["recipe:door"]
    assert host.engine.agents[0].knowledge == []
    assert host.engine.world.known_recipes(agent_id) == []

    refused = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={
            "kind": "remove_information",
            "agent_id": agent_id,
            "facts": ["fire is hot"],
        },
    )
    assert refused.status_code == 400


def test_introduce_object_places_it_on_the_grid(client):
    world = create(client, agents=1)
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    grid = host.engine.world
    spot = next(
        (x, y)
        for y in range(1, grid.height - 1)
        for x in range(1, grid.width - 1)
        if grid.is_floor(Position(x, y))
        and grid.object_at(Position(x, y)) is None
        and grid.entity_at(Position(x, y)) is None
    )

    result = intervene(
        client,
        world["id"],
        kind="introduce_object",
        object_type="tree",
        x=spot[0],
        y=spot[1],
        quantity=9,
    )

    assert result["object"]["type"] == "tree"
    assert result["object"]["properties"]["quantity"] == 9
    assert result["intervention"]["delta"]["objects"] == 1
    assert grid.object_at(Position(*spot)).type == "tree"

    occupied = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={
            "kind": "introduce_object",
            "object_type": "stone",
            "x": spot[0],
            "y": spot[1],
        },
    )
    assert occupied.status_code == 400


def test_give_task_changes_the_goal_the_agent_carries(client):
    world = create(client, agents=1)
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    agent = host.engine.agents[0]

    result = intervene(
        client,
        world["id"],
        kind="give_task",
        agent_id=agent.agent_id,
        task="build a shelter before winter",
    )

    assert result["task"] == "build a shelter before winter"
    assert agent.goal == "build a shelter before winter"
    assert result["intervention"]["details"]["previous_goal"] is None
    assert agent.observe()["self"]["goal"] == "build a shelter before winter"


def test_join_and_leave_a_population(client):
    world = create(
        client,
        populations=[{"name": "Settlers", "members": 1}],
        agents=0,
    )
    population = client.get(
        f"/api/worlds/{world['id']}/populations"
    ).json()["populations"][0]
    population_id = population["population_id"]

    missing_participant = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={"kind": "join_population", "population_id": population_id},
    )
    assert missing_participant.status_code == 409

    joined_world = client.post(
        f"/api/worlds/{world['id']}/participant/join"
    ).json()
    assert joined_world["joined"] is True

    joined = intervene(
        client,
        world["id"],
        kind="join_population",
        population_id=population_id,
    )
    assert joined["joined"] is True
    assert joined["participant"]["population_id"] == population_id
    assert joined["intervention"]["target"] == population_id

    duplicate = intervene(
        client,
        world["id"],
        kind="join_population",
        population_id=population_id,
    )
    assert duplicate["joined"] is False

    left = intervene(client, world["id"], kind="leave_population")
    assert left["left"] is True
    assert left["participant"]["population_id"] is None

    unknown = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={"kind": "join_population", "population_id": 9999},
    )
    assert unknown.status_code == 404


def test_listing_and_refusals(client):
    world = create(client, agents=1)
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
    agent_id = host.engine.agents[0].agent_id
    first = intervene(
        client,
        world["id"],
        kind="provide_information",
        agent_id=agent_id,
        facts=["stone is heavy"],
    )

    listed = client.get(f"/api/worlds/{world['id']}/interventions").json()
    assert [item["id"] for item in listed["interventions"]] == [
        first["intervention"]["id"]
    ]
    assert listed["interventions"][0]["baseline"]["knowledge_facts"] == 0

    assert client.get(
        f"/api/worlds/{world['id']}/interventions/999"
    ).status_code == 404
    unknown = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={"kind": "smite", "agent_id": agent_id},
    )
    assert unknown.status_code == 400
    missing_agent = client.post(
        f"/api/worlds/{world['id']}/interventions",
        json={"kind": "give_task", "agent_id": 999, "task": "wander"},
    )
    assert missing_agent.status_code == 404
    assert client.post(
        "/api/worlds/9999/interventions",
        json={"kind": "leave_population"},
    ).status_code == 404


def test_participant_population_survives_save_and_restore(client):
    world = create(
        client,
        populations=[{"name": "Settlers", "members": 1}],
        agents=0,
    )
    population = client.get(
        f"/api/worlds/{world['id']}/populations"
    ).json()["populations"][0]
    client.post(f"/api/worlds/{world['id']}/participant/join")
    intervene(
        client,
        world["id"],
        kind="join_population",
        population_id=population["population_id"],
    )
    host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]

    restored = type(host.engine.world).from_dict(host.engine.world.to_dict())

    assert restored.population_of(PARTICIPANT_ENTITY_ID) == population["population_id"]
    assert [item.kind for item in restored.interventions] == ["join_population"]
