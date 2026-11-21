"""The experiment worker: simulation execution in its own process.

The API enqueues (``POST /api/experiments``); this process claims queued
experiments from the database, runs them through the scenario catalog,
and writes the results back. The API never runs a study unless a client
explicitly asks to wait — so a 10,000-tick study can't make the console
hang, and the API can restart while a worker keeps simulating.

    python -m app.worker [--once] [--poll-interval 1.0] [--max-jobs N]

``--once`` drains the queue (runs everything currently queued) and exits;
without it the worker polls forever. Claiming is an atomic conditional
UPDATE, so several workers can share one queue without double-claiming
(S48 builds on that).

Status flow: queued -> running -> completed | failed. A failed run keeps
its error in ``result`` for inspection through the API.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.experiments.catalog import SCENARIOS
from app.persistence.models import ExperimentModel


def enqueue(session_factory, scenario: str, params: dict, name: str | None) -> int:
    """Create a queued experiment row. The API uses this too."""
    placeholder = f"{scenario}-{params.get('seed', 'queued')}"
    with session_factory() as session:
        row = ExperimentModel(
            # the name column is NOT NULL; unnamed jobs carry a placeholder
            # until the runner (on completion) gives the study its own name
            name=name or placeholder,
            scenario=scenario,
            seed=str(params.get("seed", "")),
            status="queued",
            model_configuration={
                "params": params,
                "name": name,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        session.add(row)
        session.commit()
        return row.id


def claim_next(session_factory) -> int | None:
    """Atomically move the oldest queued experiment to running.

    The conditional UPDATE ... RETURNING means two workers racing on one
    queue cannot both win: whoever's UPDATE matches zero rows gets None.
    """
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        oldest_queued = (
            select(ExperimentModel.id)
            .where(ExperimentModel.status == "queued")
            .order_by(ExperimentModel.id)
            .limit(1)
        )
        result = session.execute(
            update(ExperimentModel)
            .where(
                ExperimentModel.id.in_(oldest_queued),
                ExperimentModel.status == "queued",
            )
            .values(status="running", started_at=now)
            .returning(ExperimentModel.id)
        )
        claimed = result.scalars().all()
        session.commit()
    return claimed[0] if claimed else None


def run_claimed(session_factory, experiment_id: int) -> str:
    """Run one claimed experiment to completion or failure.

    Returns the outcome status ('completed' | 'failed').
    """
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None or row.status != "running":
            return "skipped"
        scenario_name = row.scenario
        configuration = dict(row.model_configuration or {})
    params = configuration.get("params") or {}
    name = configuration.get("name")

    scenario = SCENARIOS.get(scenario_name)
    if scenario is None:
        _mark_failed(session_factory, experiment_id, f"unknown scenario {scenario_name!r}")
        return "failed"

    try:
        scenario.runner(session_factory, params, name, experiment_id=experiment_id)
    except Exception as exc:  # a failing study is data, not a crash
        _mark_failed(session_factory, experiment_id, f"{type(exc).__name__}: {exc}")
        return "failed"
    return "completed"


def _mark_failed(session_factory, experiment_id: int, message: str) -> None:
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None:
            return
        row.status = "failed"
        row.finished_at = datetime.now(timezone.utc)
        row.result = {"error": message}
        session.commit()


def run_worker(
    session_factory,
    *,
    once: bool = False,
    poll_interval: float = 1.0,
    max_jobs: int | None = None,
) -> dict:
    """Claim-and-run until the queue is drained (``once``) or forever.

    Returns the outcome tally so tests and callers can assert on it.
    """
    tally = {"completed": 0, "failed": 0}
    while True:
        experiment_id = claim_next(session_factory)
        if experiment_id is None:
            if once:
                return tally
            time.sleep(poll_interval)
            continue
        outcome = run_claimed(session_factory, experiment_id)
        print(f"[worker] experiment {experiment_id}: {outcome}", flush=True)
        if outcome in tally:
            tally[outcome] += 1
        if max_jobs is not None and sum(tally.values()) >= max_jobs:
            return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.worker",
        description="Run queued experiments outside the API process (roadmap S47).",
    )
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-jobs", type=int, default=None)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    print("[worker] polling for queued experiments", flush=True)
    tally = run_worker(
        SessionLocal,
        once=args.once,
        poll_interval=args.poll_interval,
        max_jobs=args.max_jobs,
    )
    print(f"[worker] done: {tally}", flush=True)


if __name__ == "__main__":
    main()
