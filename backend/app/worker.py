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
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.experiments.catalog import SCENARIOS
from app.persistence.models import ExperimentModel
from app.profiles import get_profile


def enqueue(
    session_factory,
    scenario: str,
    params: dict,
    name: str | None,
    profile: str | None = None,
) -> int:
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
                "profile": profile,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        session.add(row)
        session.commit()
        return row.id


def claim_next(session_factory, worker_id: str | None = None) -> int | None:
    """Atomically move the oldest queued experiment to running.

    The conditional UPDATE ... RETURNING means two workers racing on one
    queue cannot both win: whoever's UPDATE matches zero rows gets None.
    With a ``worker_id``, the claim records a lease (S50): worker,
    attempt, heartbeat — the recovery system's ability to tell an
    orphaned run from a live one hangs on this.
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
        if claimed and worker_id:
            row = session.get(ExperimentModel, claimed[0])
            configuration = dict(row.model_configuration or {})
            previous = configuration.get("lease") or {}
            configuration["lease"] = {
                "worker_id": worker_id,
                "attempt": int(previous.get("attempt", 0)) + 1,
                "heartbeat_at": now.isoformat(),
                "claimed_at": now.isoformat(),
            }
            row.model_configuration = configuration
        session.commit()
    return claimed[0] if claimed else None


def touch_lease(session_factory, experiment_id: int, worker_id: str) -> bool:
    """A live worker's heartbeat: freshen the lease's heartbeat stamp.

    Only the lease's own holder may freshen it — a touch never
    resurrects the lease of a run recovery has already released.
    """
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None or row.status != "running":
            return False
        configuration = dict(row.model_configuration or {})
        lease = configuration.get("lease")
        if not lease or lease.get("worker_id") != worker_id:
            return False
        # Copy before mutating: the nested dict is shared with the
        # attribute's loaded value, and SQLAlchemy only flushes an
        # assignment whose value differs from what it loaded.
        updated = {**lease, "heartbeat_at": now.isoformat()}
        configuration["lease"] = updated
        row.model_configuration = configuration
        session.commit()
        return True


def clear_lease(session_factory, experiment_id: int, worker_id: str | None = None) -> None:
    """Drop the lease once the run reaches a terminal state."""
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None:
            return
        configuration = dict(row.model_configuration or {})
        if "lease" not in configuration:
            return
        if worker_id is not None:
            lease = configuration.get("lease") or {}
            if lease.get("worker_id") != worker_id:
                return
        configuration.pop("lease")
        row.model_configuration = configuration
        session.commit()


def recover_orphans(
    session_factory,
    *,
    lease_timeout_s: float = 60.0,
    now: datetime | None = None,
    max_attempts: int = 3,
) -> list[dict]:
    """Find running experiments whose lease has gone stale and recover them.

    A stale orphan is re-queued with its attempt count preserved (the
    next claim counts as a new attempt); a run abandoned ``max_attempts``
    times becomes a failed row whose error says so — recovery never
    loops forever. Running rows from before leases existed (no lease at
    all) are aged by ``started_at`` instead.

    Returns one record per action taken:
    ``{"experiment_id", "action": "requeued" | "failed", "attempt"}``.
    """
    now = now or datetime.now(timezone.utc)
    actions: list[dict] = []
    with session_factory() as session:
        running = (
            session.query(ExperimentModel)
            .filter(ExperimentModel.status == "running")
            .order_by(ExperimentModel.id)
            .all()
        )
        for row in running:
            configuration = dict(row.model_configuration or {})
            lease = configuration.get("lease")
            if lease:
                stamp = _parse_stamp(lease.get("heartbeat_at"))
                stale = stamp is None or (now - stamp).total_seconds() > lease_timeout_s
            else:
                stamp = row.started_at
                if stamp is not None and stamp.tzinfo is None:
                    # SQLite hands naive datetimes back; recovery's clock is UTC-aware
                    stamp = stamp.replace(tzinfo=timezone.utc)
                stale = stamp is not None and (now - stamp).total_seconds() > lease_timeout_s
            if not stale:
                continue
            attempt = int((lease or {}).get("attempt", 1))
            if attempt >= max_attempts:
                row.status = "failed"
                row.finished_at = now
                row.result = {
                    "error": (
                        f"abandoned after {attempt} attempts: the worker "
                        f"holding this run stopped heartbeating"
                    )
                }
                action = "failed"
            else:
                row.status = "queued"
                row.started_at = None
                configuration["lease"] = {
                    **(lease or {}),
                    "attempt": attempt,
                    "released_at": now.isoformat(),
                }
                row.model_configuration = configuration
                action = "requeued"
            actions.append(
                {"experiment_id": row.id, "action": action, "attempt": attempt}
            )
        session.commit()
    return actions


def _parse_stamp(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _heartbeat_loop(
    session_factory, experiment_id: int, worker_id: str, interval: float, stop
) -> None:
    """Freshen the lease every ``interval`` seconds until stopped."""
    while not stop.wait(interval):
        try:
            touch_lease(session_factory, experiment_id, worker_id)
        except Exception:  # a missed beat must never kill a run
            continue


def run_claimed(
    session_factory,
    experiment_id: int,
    profile: str | None = None,
    *,
    worker_id: str | None = None,
    heartbeat_interval: float | None = None,
) -> str:
    """Run one claimed experiment to completion or failure.

    ``profile`` is the worker's default; a run enqueued with an explicit
    profile overrides it. With a ``worker_id`` (and, optionally, a
    ``heartbeat_interval`` — default 2.0 s), the lease is kept fresh in
    a background thread for the whole run, so recovery can tell this
    live worker from an orphaned one. Returns the outcome status
    ('completed' | 'failed').
    """
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None or row.status != "running":
            return "skipped"
        scenario_name = row.scenario
        configuration = dict(row.model_configuration or {})
    params = configuration.get("params") or {}
    name = configuration.get("name")
    requested = configuration.get("profile") or profile

    scenario = SCENARIOS.get(scenario_name)
    if scenario is None:
        _mark_failed(session_factory, experiment_id, f"unknown scenario {scenario_name!r}")
        return "failed"

    stop = None
    heartbeat = None
    if worker_id is not None:
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(
                session_factory,
                experiment_id,
                worker_id,
                heartbeat_interval if heartbeat_interval is not None else 2.0,
                stop,
            ),
            daemon=True,
        )
        heartbeat.start()
    try:
        scenario.runner(
            session_factory, params, name, experiment_id=experiment_id, profile=requested
        )
    except Exception as exc:  # a failing study is data, not a crash
        _mark_failed(session_factory, experiment_id, f"{type(exc).__name__}: {exc}")
        return "failed"
    finally:
        if stop is not None:
            stop.set()
            heartbeat.join()
        clear_lease(session_factory, experiment_id, worker_id)
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
    profile: str | None = None,
    worker_id: str | None = None,
    heartbeat_interval: float | None = None,
) -> dict:
    """One claim loop: claim-and-run until the queue is drained
    (``once``) or forever.

    Returns the outcome tally so tests and callers can assert on it.
    ``profile`` names the hardware this loop executes for; it defaults
    each run's profile, and a run enqueued with an explicit profile
    overrides it. ``worker_id`` turns on leases and heartbeats (S50):
    claimed runs stay recoverable if this loop dies.
    """
    hardware = get_profile(profile)
    identity = worker_id or f"inline-{uuid.uuid4().hex[:8]}"
    tally = {"completed": 0, "failed": 0}
    while True:
        experiment_id = claim_next(session_factory, worker_id=identity)
        if experiment_id is None:
            if once:
                return tally
            time.sleep(poll_interval)
            continue
        outcome = run_claimed(
            session_factory,
            experiment_id,
            profile=hardware.name,
            worker_id=identity,
            heartbeat_interval=heartbeat_interval,
        )
        print(f"[worker] experiment {experiment_id}: {outcome}", flush=True)
        if outcome in tally:
            tally[outcome] += 1
        if max_jobs is not None and sum(tally.values()) >= max_jobs:
            return tally


def run_workers_parallel(
    session_factory,
    *,
    workers: int | None = None,
    once: bool = False,
    poll_interval: float = 1.0,
    max_jobs: int | None = None,
    profile: str | None = None,
    worker_id: str | None = None,
    heartbeat_interval: float | None = None,
) -> dict:
    """Run several claim loops concurrently in this process (S48/S50).

    Every loop claims through the same atomic conditional UPDATE, so the
    queue is partitioned — no experiment is claimed twice. The loop count
    comes from the hardware profile unless stated outright; threads give
    the concurrency, separate worker *processes* give the CPU scale-out.
    Each loop carries its own lease identity when ``worker_id`` (or a
    heartbeat interval) is supplied, so its runs stay recoverable.
    """
    from concurrent.futures import ThreadPoolExecutor

    hardware = get_profile(profile)
    loop_count = workers if workers is not None else hardware.workers
    base_id = worker_id or f"fleet-{uuid.uuid4().hex[:8]}"
    combined = {"completed": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=loop_count) as pool:
        tallies = list(
            pool.map(
                lambda index: run_worker(
                    session_factory,
                    once=once,
                    poll_interval=poll_interval,
                    max_jobs=max_jobs,
                    profile=hardware.name,
                    worker_id=f"{base_id}-{index}",
                    heartbeat_interval=heartbeat_interval,
                ),
                range(loop_count),
            )
        )
    for tally in tallies:
        for kind, count in tally.items():
            combined[kind] = combined.get(kind, 0) + count
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.worker",
        description="Run queued experiments outside the API process (roadmap S47).",
    )
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="concurrent claim loops in this process; defaults to the "
        "hardware profile's count (scale out further by starting more "
        "worker processes)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=["tiny", "desktop", "gpu", "cloud"],
        help="the hardware this worker executes for (S49)",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="lease identity for recovery (S50); defaults to a fresh id",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=None,
        help="seconds between lease heartbeats (default 2.0)",
    )
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    print("[worker] polling for queued experiments", flush=True)
    if args.workers is not None and args.workers > 1:
        tally = run_workers_parallel(
            SessionLocal,
            workers=args.workers,
            once=args.once,
            poll_interval=args.poll_interval,
            max_jobs=args.max_jobs,
            profile=args.profile,
            worker_id=args.worker_id,
            heartbeat_interval=args.heartbeat_interval,
        )
    else:
        tally = run_worker(
            SessionLocal,
            once=args.once,
            poll_interval=args.poll_interval,
            max_jobs=args.max_jobs,
            profile=args.profile,
            worker_id=args.worker_id,
            heartbeat_interval=args.heartbeat_interval,
        )
    print(f"[worker] done: {tally}", flush=True)


if __name__ == "__main__":
    main()
