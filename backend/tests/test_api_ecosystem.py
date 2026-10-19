"""S43 — Ecosystem API: opt-in life, the shelf, and the live summary."""

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
        f"sqlite:///{tmp_path / 'ecosystem.db'}",
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


def create(client, *, ecosystem: bool, seed: str = "eco-api") -> dict:
    response = client.post(
        "/api/worlds",
        json={
            "seed": seed, "width": 16, "height": 16,
            "agents": 2, "autostart": False, "ecosystem": ecosystem,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_ecosystem_is_off_unless_requested(client):
    plain = create(client, ecosystem=False)
    assert plain["ecosystem"] is None

    report = client.get(f"/api/worlds/{plain['id']}/ecosystem").json()
    assert report == {"world_id": plain["id"], "enabled": False}


def test_ecosystem_world_exposes_plants_animals_and_climate(client):
    created = create(client, ecosystem=True)
    ecosystem = created["ecosystem"]

    assert ecosystem["enabled"] is True
    assert ecosystem["season"] == "spring"
    assert ecosystem["weather"] in {
        "clear", "rain", "storm", "snow",
    }
    assert ecosystem["plants"]["count"] > 0
    assert ecosystem["plants"]["biomass"] <= ecosystem["plants"]["capacity"]
    assert ecosystem["animals"]["count"] > 0
    assert ecosystem["animals"]["count"] <= ecosystem["animals"]["max_total"]

    report = client.get(f"/api/worlds/{created['id']}/ecosystem").json()
    assert report["enabled"] is True
    assert report["world_id"] == created["id"]
    assert report["plants"]["count"] == ecosystem["plants"]["count"]


def test_stepping_advances_the_ecosystem(client):
    created = create(client, ecosystem=True)
    first = client.get(f"/api/worlds/{created['id']}/ecosystem").json()

    for _ in range(3):
        stepped = client.post(f"/api/worlds/{created['id']}/step")
        assert stepped.status_code == 200

    second = client.get(f"/api/worlds/{created['id']}/ecosystem").json()
    assert second["plants"]["count"] == first["plants"]["count"]  # capped shelf
    total_animals = sum(second["animals"]["by_species"].values())
    assert total_animals == second["animals"]["count"]


def test_the_ecosystem_shelf_is_public(client):
    catalog = client.get("/api/ecosystem").json()
    assert catalog["seasons"] == ["spring", "summer", "autumn", "winter"]
    assert {"grazer", "predator"} <= set(catalog["animals"])
    assert {"berry", "tree"} == set(catalog["plants"])
    assert catalog["defaults"]["max_plants"] >= 1
    assert catalog["defaults"]["max_total_animals"] >= 1
