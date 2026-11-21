"""S49 — hardware profiles: same experiment, different execution, same
outcomes.

The roadmap's contract has two halves and both are tested here. First,
the *comparable metrics* half: the identical configuration run under
Tiny and Cloud must produce identical outcome metrics — hardware cannot
alter a history — while each result records its own runtime. Second, the
plumbing: profiles validate at enqueue, ride through the worker, size
the concurrency, and land in the stored result; the compare endpoint
turns two runs into one verdict.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.experiments import router as experiments_router
from app.api.worlds import router as worlds_router
from app.experiments.multi_world import run_study as run_multi_world_study
from app.experiments.observer import run_study as run_observer_study
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.profiles import (
    HARDWARE_PROFILES,
    compare_across_profiles,
    get_profile,
)
from app.worker import enqueue, run_worker


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'profiles.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    application = FastAPI()
    application.include_router(worlds_router, prefix="/api")
    application.include_router(experiments_router, prefix="/api")
    application.state.session_factory = factory
    application.state.worlds = WorldRegistry(factory)
    with TestClient(application) as test_client:
        yield test_client, factory
    engine.dispose()


# ----------------------------------------------------------------------
# The registry
# ----------------------------------------------------------------------


def test_the_four_profiles_exist():
    assert set(HARDWARE_PROFILES) == {"tiny", "desktop", "gpu", "cloud"}


def test_the_default_profile_is_desktop():
    assert get_profile(None).name == "desktop"


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError, match="mainframe"):
        get_profile("mainframe")


def test_profiles_differ_in_concurrency():
    assert HARDWARE_PROFILES["tiny"].workers < HARDWARE_PROFILES["cloud"].workers
    assert (
        HARDWARE_PROFILES["tiny"].max_parallel_worlds
        < HARDWARE_PROFILES["cloud"].max_parallel_worlds
    )


# ----------------------------------------------------------------------
# Same configuration, different hardware: comparable metrics
# ----------------------------------------------------------------------


def test_the_same_study_under_tiny_and_cloud_matches_outcomes(session_factory):
    tiny = run_multi_world_study(
        session_factory=session_factory,
        worlds=3,
        template="void",
        seed="twin",
        ticks=8,
        profile="tiny",
    )
    cloud = run_multi_world_study(
        session_factory=session_factory,
        worlds=3,
        template="void",
        seed="twin",
        ticks=8,
        profile="cloud",
    )

    verdict = compare_across_profiles(tiny, cloud)
    assert verdict["outcomes_identical"] is True
    assert verdict["profiles"] == ["tiny", "cloud"]

    # each result knows the hardware it ran on, and the pool was sized
    # by that hardware (tiny caps at 2 parallel worlds, cloud at 8)
    assert tiny["runtime"]["profile"] == "tiny"
    assert tiny["runtime"]["workers"] == 2
    assert cloud["runtime"]["profile"] == "cloud"
    assert cloud["runtime"]["workers"] == 3  # min(3 worlds, 8)

    for runtime in (tiny["runtime"], cloud["runtime"]):
        assert runtime["duration_s"] >= 0
        assert runtime["ticks_total"] == 24
        assert runtime["tps"] > 0


def test_the_observer_pair_runs_under_a_profile(session_factory):
    study = run_observer_study(
        session_factory=session_factory,
        template="void",
        seed="paired",
        ticks=6,
        profile="tiny",
    )
    assert study["runtime"]["profile"] == "tiny"
    assert study["runtime"]["workers"] == 2  # two sides, tiny allows two
    assert study["comparison"]["differing"]


def test_differing_studies_are_not_outcome_identical(session_factory):
    tiny = run_multi_world_study(
        session_factory=session_factory,
        worlds=2,
        template="void",
        seed="one-seed",
        ticks=6,
        profile="tiny",
    )
    cloud = run_multi_world_study(
        session_factory=session_factory,
        worlds=2,
        template="void",
        seed="another-seed",
        ticks=6,
        profile="cloud",
    )
    verdict = compare_across_profiles(tiny, cloud)
    assert verdict["outcomes_identical"] is False


# ----------------------------------------------------------------------
# Through the worker and the API
# ----------------------------------------------------------------------


def test_a_requested_profile_overrides_the_worker_default(session_factory):
    experiment_id = enqueue(
        session_factory,
        "multi_world",
        {"worlds": 2, "ticks": 6, "seed": "pinned"},
        None,
        profile="cloud",
    )
    # the worker is Desktop by default; the row's request must win
    run_worker(session_factory, once=True)

    row = _row(session_factory, experiment_id)
    assert row.result["runtime"]["profile"] == "cloud"


def _row(factory, experiment_id: int):
    with factory() as session:
        return session.get(ExperimentModel, experiment_id)


def test_the_api_validates_stores_and_runs_a_profile(client):
    test_client, _ = client
    submitted = test_client.post(
        "/api/experiments",
        json={
            "scenario": "multi_world",
            "params": {"worlds": 2, "ticks": 6, "seed": "profiled"},
            "profile": "cloud",
        },
    )
    assert submitted.status_code == 202
    experiment_id = submitted.json()["experiment"]["id"]

    run_worker(test_client.app.state.session_factory, once=True)

    detail = test_client.get(f"/api/experiments/{experiment_id}").json()
    assert detail["configuration"]["profile"] == "cloud"
    assert detail["result"]["runtime"]["profile"] == "cloud"


def test_the_api_refuses_an_unknown_profile(client):
    test_client, factory = client
    response = test_client.post(
        "/api/experiments",
        json={"scenario": "multi_world", "params": {}, "profile": "mainframe"},
    )
    assert response.status_code == 400
    assert "hardware profile" in response.text
    with factory() as session:
        assert session.query(ExperimentModel).count() == 0


def test_the_compare_endpoint_verdicts_two_runs(client):
    test_client, factory = client
    ids = []
    for profile in ("tiny", "cloud"):
        submitted = test_client.post(
            "/api/experiments",
            json={
                "scenario": "multi_world",
                "params": {"worlds": 2, "ticks": 6, "seed": "same-config"},
                "profile": profile,
            },
        )
        ids.append(submitted.json()["experiment"]["id"])
    run_worker(factory, once=True)

    verdict = test_client.get(f"/api/experiments/{ids[0]}/compare/{ids[1]}").json()
    assert verdict["outcomes_identical"] is True
    assert verdict["profiles"] == ["tiny", "cloud"]
    assert verdict["runtime"]["first"]["profile"] == "tiny"
    assert verdict["runtime"]["second"]["profile"] == "cloud"
    assert [row["id"] for row in verdict["experiments"]] == ids


def test_the_compare_endpoint_refuses_resultless_runs(client):
    test_client, _ = client
    first = test_client.post(
        "/api/experiments",
        json={"scenario": "multi_world", "params": {"worlds": 2, "ticks": 6}, "profile": "tiny"},
    ).json()["experiment"]["id"]
    # the second run is queued but never executed by any worker
    second = test_client.post(
        "/api/experiments",
        json={"scenario": "multi_world", "params": {"worlds": 2, "ticks": 6}, "profile": "cloud"},
    ).json()["experiment"]["id"]

    response = test_client.get(f"/api/experiments/{first}/compare/{second}")
    assert response.status_code == 409


def test_the_compare_endpoint_404s_on_unknown_ids(client):
    test_client, _ = client
    response = test_client.get("/api/experiments/999/compare/1000")
    assert response.status_code == 404
