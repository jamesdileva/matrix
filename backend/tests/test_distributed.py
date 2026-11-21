"""S50 — the distributed laboratory: leases, recovery, an operated fleet.

The roadmap's checks, mapped to tests:

- **workers can be added/removed** — the Fleet starts and kills real
  worker processes at runtime; a removal orphans its running lease and
  the job finishes on another worker (the controller flow test);
- **failed jobs recover** — a stale lease is re-queued with its attempt
  count preserved, and a run abandoned past the attempt cap becomes a
  failed row whose error says so, instead of looping forever;
- **experiment state remains consistent** — through crashes, removals
  and retries, every row ends in exactly one terminal state, runs into
  its own row, and no lease is resurrected by the wrong worker.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.controller import Fleet, queue_state
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.worker import (
    claim_next,
    clear_lease,
    enqueue,
    recover_orphans,
    run_claimed,
    run_worker,
    touch_lease,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'distributed.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _row(factory, experiment_id: int) -> ExperimentModel:
    with factory() as session:
        return session.get(ExperimentModel, experiment_id)


def _lease(factory, experiment_id: int) -> dict:
    return (_row(factory, experiment_id).model_configuration or {}).get("lease") or {}


def _wait_for(factory, experiment_id: int, status: str, timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _row(factory, experiment_id).status == status:
            return True
        time.sleep(0.1)
    return False


# ----------------------------------------------------------------------
# Leases
# ----------------------------------------------------------------------


def test_a_claim_records_a_lease(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)

    claimed = claim_next(session_factory, worker_id="worker-one")
    assert claimed == experiment_id

    lease = _lease(session_factory, experiment_id)
    assert lease["worker_id"] == "worker-one"
    assert lease["attempt"] == 1
    assert lease["heartbeat_at"]
    assert lease["claimed_at"]


def test_the_heartbeat_freshens_only_its_own_lease(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory, worker_id="worker-one")
    before = _lease(session_factory, experiment_id)["heartbeat_at"]
    time.sleep(0.02)

    assert touch_lease(session_factory, experiment_id, "worker-one") is True
    after = _lease(session_factory, experiment_id)["heartbeat_at"]
    assert after > before

    # a stranger cannot resurrect the lease
    time.sleep(0.02)
    assert touch_lease(session_factory, experiment_id, "worker-two") is False
    assert _lease(session_factory, experiment_id)["heartbeat_at"] == after


def test_a_terminal_run_drops_its_lease(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory, worker_id="worker-one")
    run_claimed(session_factory, experiment_id, worker_id="worker-one")

    assert _row(session_factory, experiment_id).status == "completed"
    assert _lease(session_factory, experiment_id) == {}


# ----------------------------------------------------------------------
# Recovery
# ----------------------------------------------------------------------


def test_a_stale_lease_is_requeued_and_attempts_count(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)

    claim_next(session_factory, worker_id="worker-one")  # attempt 1
    later = datetime.now(timezone.utc) + timedelta(seconds=300)
    actions = recover_orphans(session_factory, lease_timeout_s=10.0, now=later)
    assert actions == [{"experiment_id": experiment_id, "action": "requeued", "attempt": 1}]

    row = _row(session_factory, experiment_id)
    assert row.status == "queued"

    # the next claim is attempt 2 — the count survived the requeue
    assert claim_next(session_factory, worker_id="worker-two") == experiment_id
    assert _lease(session_factory, experiment_id)["attempt"] == 2
    assert _lease(session_factory, experiment_id)["worker_id"] == "worker-two"


def test_a_run_abandoned_past_the_cap_fails(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    later = datetime.now(timezone.utc) + timedelta(seconds=300)

    for attempt in range(3):  # claim, abandon, claim, abandon, claim, abandon
        assert claim_next(session_factory, worker_id=f"worker-{attempt}") == experiment_id
        actions = recover_orphans(session_factory, lease_timeout_s=10.0, now=later)
        expected = "requeued" if attempt < 2 else "failed"
        assert actions[0]["action"] == expected

    row = _row(session_factory, experiment_id)
    assert row.status == "failed"
    assert "abandoned after 3 attempts" in row.result["error"]


def test_a_fresh_lease_is_left_alone(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory, worker_id="worker-one")
    touch_lease(session_factory, experiment_id, "worker-one")

    actions = recover_orphans(session_factory, lease_timeout_s=60.0)
    assert actions == []
    assert _row(session_factory, experiment_id).status == "running"


def test_a_leaseless_running_row_is_recovered_by_age(session_factory):
    """Running rows from before leases existed are aged by started_at."""
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory)  # no worker id: no lease
    assert _lease(session_factory, experiment_id) == {}

    actions = recover_orphans(
        session_factory,
        lease_timeout_s=10.0,
        now=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    assert actions == [{"experiment_id": experiment_id, "action": "requeued", "attempt": 1}]
    assert _row(session_factory, experiment_id).status == "queued"


def test_a_recovered_job_finishes_its_own_row(session_factory):
    experiment_id = enqueue(session_factory, "observer_vs_participant", {"ticks": 6}, None)

    claim_next(session_factory, worker_id="worker-one")  # dies, conceptually
    recover_orphans(
        session_factory,
        lease_timeout_s=10.0,
        now=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    assert claim_next(session_factory, worker_id="worker-two") == experiment_id
    run_claimed(session_factory, experiment_id, worker_id="worker-two")

    row = _row(session_factory, experiment_id)
    assert row.status == "completed"
    assert row.result["comparison"]["differing"]
    assert _lease(session_factory, experiment_id) == {}


# ----------------------------------------------------------------------
# The fleet: workers added, removed, and the job that survives both
# ----------------------------------------------------------------------


def test_the_fleet_survives_a_worker_removal(tmp_path):
    """The roadmap's flow, live: add a worker, let it claim a long study,
    remove it mid-run, recover, add a replacement — the study completes,
    once, in its own row."""
    db_path = tmp_path / "fleet.db"
    url = f"sqlite:///{db_path}"
    owner = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(owner)
    factory = sessionmaker(bind=owner, expire_on_commit=False)
    experiment_id = enqueue(
        factory, "multi_world", {"worlds": 1, "ticks": 6000, "seed": "fleet"}, "survivor"
    )

    fleet = Fleet(
        db_url=url,
        profile="desktop",
        workers=0,
        heartbeat_interval=0.5,
        lease_timeout_s=3.0,
        backend_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    try:
        (worker_id,) = fleet.add_worker(1)
        assert _wait_for(factory, experiment_id, "running", timeout_s=30)
        assert _lease(factory, experiment_id)["worker_id"] == worker_id

        # remove the worker mid-run: the lease goes stale, the controller
        # re-queues, the replacement worker finishes the job
        fleet.remove_worker(worker_id)
        deadline = time.time() + 30
        while time.time() < deadline and _row(factory, experiment_id).status == "running":
            fleet.recover(factory)
            time.sleep(0.5)
        assert _row(factory, experiment_id).status in {"queued", "completed"}

        fleet.add_worker(1)
        assert _wait_for(factory, experiment_id, "completed", timeout_s=120)
    finally:
        fleet.shutdown()

    row = _row(factory, experiment_id)
    assert row.status == "completed"
    assert row.name == "survivor"
    assert row.result["runs"][0]["ticks"] == 6000
    assert _lease(factory, experiment_id) == {}

    state = queue_state(factory)
    assert state["running"] == 0
    assert state["completed"] == 1
    assert state["queued"] == 0


def test_queue_state_reflects_every_status(session_factory):
    completed = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory, worker_id="w")
    run_claimed(session_factory, completed, worker_id="w")
    running = enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)
    claim_next(session_factory, worker_id="w")
    enqueue(session_factory, "observer_vs_participant", {"ticks": 4}, None)

    state = queue_state(session_factory)
    assert state == {"queued": 1, "running": 1, "completed": 1, "failed": 0}


def test_fleet_state_reports_fleet_and_queue(tmp_path):
    db_path = tmp_path / "state.db"
    url = f"sqlite:///{db_path}"
    owner = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(owner)
    factory = sessionmaker(bind=owner, expire_on_commit=False)

    fleet = Fleet(db_url=url, profile="tiny", workers=0)
    try:
        fleet.add_worker(2)
        state = fleet.state(factory)
        assert state["profile"] == "tiny"
        assert len(state["workers"]) == 2
        assert state["queue"]["completed"] == 0
    finally:
        fleet.shutdown()
        owner.dispose()
    assert fleet.worker_ids() == []
