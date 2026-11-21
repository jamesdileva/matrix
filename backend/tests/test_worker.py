"""S47 — the experiment worker: simulation out of the API process.

The roadmap's checks: the simulation can run independently (its own
process, claiming from the database), and the API stays responsive while
it does. The enqueue→claim→complete loop is tested here in-process; the
subprocess test proves the worker really is a separate program; the
"API responsive" property is exercised live in the sprint verification.
"""

import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.experiments import router as experiments_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.worker import claim_next, enqueue, run_claimed, run_worker


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}",
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


def _status(factory, experiment_id: int) -> ExperimentModel:
    with factory() as session:
        return session.get(ExperimentModel, experiment_id)


# ----------------------------------------------------------------------
# claim and run
# ----------------------------------------------------------------------


def test_claim_moves_the_oldest_queued_to_running(session_factory):
    first = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, "job-a")
    enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, "job-b")

    claimed = claim_next(session_factory)
    assert claimed == first
    row = _status(session_factory, first)
    assert row.status == "running"
    assert row.started_at is not None

    # the second job is still waiting
    assert _status(session_factory, first + 1).status == "queued"


def test_claim_on_an_empty_queue_returns_none(session_factory):
    assert claim_next(session_factory) is None


def test_run_claimed_completes_a_study(session_factory):
    experiment_id = enqueue(
        session_factory, "observer_vs_participant", {"ticks": 6}, "pair-study"
    )
    claim_next(session_factory)

    outcome = run_claimed(session_factory, experiment_id)
    assert outcome == "completed"

    row = _status(session_factory, experiment_id)
    assert row.status == "completed"
    assert row.finished_at is not None
    assert row.name == "pair-study"
    assert row.result["comparison"]["dimensions"]["development"]["delta"]["entities"] >= 1
    assert row.model_configuration["participant_plan"]  # the study's own config


def test_a_failing_study_becomes_a_failed_row(session_factory):
    # vary=template without one template per world is refused by the study
    experiment_id = enqueue(
        session_factory,
        "multi_world",
        {"worlds": 3, "vary": "template", "ticks": 5},
        None,
    )
    claim_next(session_factory)

    outcome = run_claimed(session_factory, experiment_id)
    assert outcome == "failed"

    row = _status(session_factory, experiment_id)
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "ValueError" in row.result["error"]


def test_run_claimed_skips_rows_it_did_not_claim(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    # never claimed: still queued, so the worker refuses to touch it
    assert run_claimed(session_factory, experiment_id) == "skipped"
    assert _status(session_factory, experiment_id).status == "queued"


def test_run_worker_drains_the_queue(session_factory):
    for index in range(3):
        enqueue(
            session_factory, "observer_vs_participant", {"ticks": 4}, f"batch-{index}"
        )

    tally = run_worker(session_factory, once=True)

    assert tally == {"completed": 3, "failed": 0}
    with session_factory() as session:
        statuses = [
            row.status
            for row in session.query(ExperimentModel).order_by(ExperimentModel.id)
        ]
    assert statuses == ["completed", "completed", "completed"]
    assert claim_next(session_factory) is None  # nothing left


# ----------------------------------------------------------------------
# Through the API: enqueue by default, wait on request
# ----------------------------------------------------------------------


def test_the_api_enqueues_by_default_and_the_worker_finishes_it(client):
    test_client, factory = client
    submitted = test_client.post(
        "/api/experiments",
        json={"scenario": "observer_vs_participant", "params": {"ticks": 6}},
    )
    assert submitted.status_code == 202
    body = submitted.json()
    assert body["queued"] is True
    experiment_id = body["experiment"]["id"]
    assert body["experiment"]["status"] == "queued"

    # the API answered instantly with a queued row; the worker does the work
    tally = run_worker(factory, once=True)
    assert tally == {"completed": 1, "failed": 0}

    detail = test_client.get(f"/api/experiments/{experiment_id}").json()
    assert detail["status"] == "completed"
    assert detail["result"]["comparison"]["differing"]
    assert detail["result"]["participant"]["measures"]["participant_actions"] > 0


def test_wait_true_still_runs_inline(client):
    test_client, _ = client
    response = test_client.post(
        "/api/experiments",
        json={
            "scenario": "observer_vs_participant",
            "params": {"ticks": 6},
            "wait": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["study"]["comparison"]["differing"]


def test_an_unknown_scenario_is_refused_before_enqueueing(client):
    test_client, factory = client
    response = test_client.post(
        "/api/experiments", json={"scenario": "nope", "params": {}}
    )
    assert response.status_code == 404
    with factory() as session:
        assert session.query(ExperimentModel).count() == 0


# ----------------------------------------------------------------------
# The worker as its own process
# ----------------------------------------------------------------------


def test_the_worker_runs_as_an_independent_process(tmp_path):
    """No FastAPI, no test client: one Python process enqueueing, another
    claiming from the same database file and finishing the study."""
    db_path = tmp_path / "independent.db"
    url = f"sqlite:///{db_path}"

    owner = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(owner)
    factory = sessionmaker(bind=owner, expire_on_commit=False)
    experiment_id = enqueue(
        factory, "observer_vs_participant", {"ticks": 5}, "lone-job"
    )
    owner.dispose()

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "FLOOD_DATABASE_URL": url, "PYTHONPATH": backend_root}
    completed = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    assert "[worker] done: {'completed': 1, 'failed': 0}" in completed.stdout

    check = create_engine(url, connect_args={"check_same_thread": False})
    with sessionmaker(bind=check, expire_on_commit=False)() as session:
        row = session.get(ExperimentModel, experiment_id)
        assert row.status == "completed"
        assert row.result["experiment_id"] == experiment_id
    check.dispose()
