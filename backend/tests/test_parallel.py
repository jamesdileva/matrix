"""S48 — parallel experiments: concurrency, isolation, budgets, attribution.

Three properties under test, straight from the roadmap:

- **experiments remain isolated** — studies running concurrently produce
  byte-identical results to their serial runs (determinism makes any
  cross-contamination visible), and racing claimants never share a job;
- **resource budgets are respected** — a capped study stops at exactly
  its ceiling, ledger arithmetic precise, and two concurrent studies
  never draw on each other's budget;
- **results remain attributable** — each row carries its own study's
  result, seed and params, whether the queue was drained by one worker
  or three.
"""

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.experiments.multi_world import run_study as run_multi_world_study
from app.experiments.observer import run_study as run_observer_study
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.worker import enqueue, run_workers_parallel, run_worker


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'parallel.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _row(factory, experiment_id: int) -> ExperimentModel:
    with factory() as session:
        return session.get(ExperimentModel, experiment_id)


# ----------------------------------------------------------------------
# Racing claimants
# ----------------------------------------------------------------------


def test_parallel_claimants_partition_the_queue(session_factory):
    for index in range(8):
        enqueue(
            session_factory,
            "observer_vs_participant",
            {"ticks": 4},
            f"race-{index}",
        )

    tally = run_workers_parallel(session_factory, workers=4, once=True)

    assert tally["completed"] == 8
    assert tally["failed"] == 0
    with session_factory() as session:
        rows = session.query(ExperimentModel).order_by(ExperimentModel.id).all()
    assert [row.status for row in rows] == ["completed"] * 8
    # every study filled its own row: the names survived the race
    assert sorted(row.name for row in rows) == [f"race-{i}" for i in range(8)]


def test_worker_processes_partition_one_queue(tmp_path):
    """Three worker *processes* race on one database file. Every job is
    completed exactly once and the claimed ids are disjoint."""
    db_path = tmp_path / "race.db"
    url = f"sqlite:///{db_path}"
    owner = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(owner)
    factory = sessionmaker(bind=owner, expire_on_commit=False)
    ids = [
        enqueue(factory, "observer_vs_participant", {"ticks": 4}, f"proc-{index}")
        for index in range(6)
    ]
    owner.dispose()

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "FLOOD_DATABASE_URL": url, "PYTHONPATH": backend_root}
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "app.worker", "--once", "--workers", "2"],
            cwd=backend_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=300)
        assert process.returncode == 0, stderr
        outputs.append(stdout)

    claimed = []
    for stdout in outputs:
        claimed += [
            int(line.split("experiment ")[1].split(":")[0])
            for line in stdout.splitlines()
            if line.startswith("[worker] experiment ")
        ]
    assert sorted(claimed) == sorted(ids)  # every job ran, none twice

    check = create_engine(url, connect_args={"check_same_thread": False})
    with sessionmaker(bind=check, expire_on_commit=False)() as session:
        rows = session.query(ExperimentModel).order_by(ExperimentModel.id).all()
    assert [row.status for row in rows] == ["completed"] * 6
    check.dispose()


# ----------------------------------------------------------------------
# Isolation and attribution: parallel == serial
# ----------------------------------------------------------------------


def _canonical(study: dict) -> dict:
    """A study minus the keys that legitimately differ between two runs
    of the same params: its row id, any caller-assigned name, and the
    S49 runtime (wall-clock facts — duration and throughput are supposed
    to vary; the outcome metrics are not)."""
    body = json.loads(json.dumps(study))
    body.pop("experiment_id", None)
    body.pop("name", None)
    body.pop("runtime", None)
    for run in body.get("runs", []):
        run.pop("experiment_id", None)
    return body


def test_concurrent_studies_match_their_serial_runs(session_factory):
    """The same two studies, first serially, then raced — every result
    byte-identical, every row carrying its own study."""
    serial = {
        "observer": run_observer_study(
            session_factory=session_factory, template="void", seed="alpha", ticks=6
        ),
        "multi_world": run_multi_world_study(
            session_factory=session_factory,
            worlds=3,
            template="void",
            seed="beta",
            ticks=6,
        ),
    }

    # fresh queue on the same database; the serial rows stay for comparison
    observer_id = enqueue(
        session_factory, "observer_vs_participant", {"ticks": 6, "seed": "alpha"}, None
    )
    multi_id = enqueue(
        session_factory, "multi_world", {"worlds": 3, "ticks": 6, "seed": "beta"}, None
    )
    run_workers_parallel(session_factory, workers=2, once=True)

    raced_observer = _row(session_factory, observer_id)
    raced_multi = _row(session_factory, multi_id)

    # attribution: each row carries its own study, not its neighbour's
    assert raced_observer.result["seed"] == "alpha"
    assert raced_multi.result["seed"] == "beta"
    assert raced_observer.scenario == "observer_vs_participant"
    assert raced_multi.scenario == "multi_world"

    # isolation: raced results are byte-identical to the serial ones
    assert _canonical(raced_observer.result) == _canonical(serial["observer"])
    assert _canonical(raced_multi.result) == _canonical(serial["multi_world"])


def test_parallel_worlds_inside_a_study_are_deterministic(session_factory):
    first = run_multi_world_study(
        session_factory=session_factory, worlds=6, template="void", seed="pool", ticks=8
    )
    second = run_multi_world_study(
        session_factory=session_factory, worlds=6, template="void", seed="pool", ticks=8
    )

    # the thread pool preserves index order and never perturbs a world
    assert [run["index"] for run in first["runs"]] == list(range(6))
    assert _canonical(first) == _canonical(second)


# ----------------------------------------------------------------------
# Resource budgets
# ----------------------------------------------------------------------


def test_a_capped_study_stops_at_exactly_its_ceiling(session_factory):
    capped = run_multi_world_study(
        session_factory=session_factory,
        worlds=2,
        template="void",
        seed="capped",
        ticks=80,
        max_actions=20,
    )
    unlimited = run_multi_world_study(
        session_factory=session_factory, worlds=2, template="void", seed="capped", ticks=80
    )

    for run in capped["runs"]:
        # the ledger stopped at precisely the ceiling, and the world
        # never executed more than it was allowed
        assert run["actions_spent"] == 20
        assert run["actions"] <= 20
        assert run["rejections"] > 0  # refusals, not crashes
    assert capped["runs"][0]["max_actions"] == 20

    total_capped = sum(run["actions"] for run in capped["runs"])
    total_free = sum(run["actions"] for run in unlimited["runs"])
    assert total_free > total_capped  # the cap actually bit
    assert unlimited["runs"][0]["actions_spent"] is None


def test_concurrent_studies_have_independent_budgets(session_factory):
    """Two capped studies raced on the queue: neither outspends its own
    ceiling, and neither spends the other's allowance."""
    for index in range(2):
        enqueue(
            session_factory,
            "multi_world",
            {"worlds": 1, "ticks": 60, "seed": f"budget-{index}", "max_actions": 15},
            None,
        )
    run_workers_parallel(session_factory, workers=2, once=True)

    with session_factory() as session:
        rows = session.query(ExperimentModel).order_by(ExperimentModel.id).all()
    for row in rows:
        for run in row.result["runs"]:
            assert run["actions_spent"] == 15
            assert run["actions"] <= 15


# ----------------------------------------------------------------------
# The worker CLI, concurrently
# ----------------------------------------------------------------------


def test_worker_cli_runs_multiple_claim_loops(tmp_path):
    """`python -m app.worker --once --workers 3` drains a queue through
    three concurrent claim loops in one process."""
    db_path = tmp_path / "cli.db"
    url = f"sqlite:///{db_path}"
    owner = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(owner)
    factory = sessionmaker(bind=owner, expire_on_commit=False)
    ids = [
        enqueue(factory, "observer_vs_participant", {"ticks": 4}, f"cli-{index}")
        for index in range(5)
    ]
    owner.dispose()

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "FLOOD_DATABASE_URL": url, "PYTHONPATH": backend_root}
    completed = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once", "--workers", "3"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert "[worker] done: {'completed': 5, 'failed': 0}" in completed.stdout

    check = create_engine(url, connect_args={"check_same_thread": False})
    with sessionmaker(bind=check, expire_on_commit=False)() as session:
        rows = session.query(ExperimentModel).order_by(ExperimentModel.id).all()
    assert [row.status for row in rows] == ["completed"] * 5
    assert [row.name for row in rows] == [f"cli-{i}" for i in range(5)]
    check.dispose()
