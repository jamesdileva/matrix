"""The controller: operating a fleet of workers (S50).

The roadmap's distributed laboratory — a controller over a queue, over
workers, each running worlds. The fleet is same-machine subprocesses
sharing one database (the roadmap's "only if justified" is honoured: no
network transport), but the shape is the architecture: workers are
added and removed at runtime, an orphaned run is recovered by whoever
notices it, and every experiment ends in exactly one terminal state.

    fleet = Fleet(db_url="sqlite:///./flood.db", profile="desktop")
    fleet.add_worker()
    fleet.state()
    fleet.recover()
    fleet.shutdown()
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from app.persistence.models import ExperimentModel
from app.worker import recover_orphans

DEFAULT_LEASE_TIMEOUT_S = 30.0


def queue_state(session_factory) -> dict:
    """The queue's shape: counts by status — the consistency at a glance."""
    with session_factory() as session:
        counts = dict(
            session.query(ExperimentModel.status, func.count(ExperimentModel.id))
            .group_by(ExperimentModel.status)
            .all()
        )
    return {
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
    }


class Fleet:
    """A set of worker subprocesses this controller owns.

    Each worker is `python -m app.worker` pointed at the fleet's database
    with its own lease identity and heartbeat; removing a worker kills
    the process, and its orphaned run is recovered exactly like any other
    abandoned lease — by `recover`, by another worker, or by the next
    controller that looks.
    """

    def __init__(
        self,
        *,
        db_url: str | None = None,
        profile: str = "desktop",
        workers: int = 1,
        heartbeat_interval: float = 2.0,
        lease_timeout_s: float = DEFAULT_LEASE_TIMEOUT_S,        backend_root: str | None = None,
    ) -> None:
        self.db_url = db_url
        self.profile = profile
        self.heartbeat_interval = heartbeat_interval
        self.lease_timeout_s = lease_timeout_s
        self.backend_root = backend_root or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        self.name = f"controller-{uuid.uuid4().hex[:8]}"
        self._workers: dict[str, subprocess.Popen] = {}
        if workers > 0:
            self.add_worker(workers)

    # ------------------------------------------------------------------
    # Fleet membership
    # ------------------------------------------------------------------

    def add_worker(self, count: int = 1) -> list[str]:
        """Start `count` worker subprocesses; returns their lease ids."""
        added = []
        for _ in range(count):
            worker_id = f"{self.name}-{uuid.uuid4().hex[:6]}"
            env = {**os.environ}
            if self.db_url:
                env["FLOOD_DATABASE_URL"] = self.db_url
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.worker",
                    "--worker-id",
                    worker_id,
                    "--profile",
                    self.profile,
                    "--heartbeat-interval",
                    str(self.heartbeat_interval),
                ],
                cwd=self.backend_root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._workers[worker_id] = process
            added.append(worker_id)
        return added

    def remove_worker(self, worker_id: str) -> bool:
        """Stop a worker process. Its running lease goes stale and is
        recovered by `recover` — the job is never lost."""
        process = self._workers.pop(worker_id, None)
        if process is None:
            return False
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return True

    def worker_ids(self) -> list[str]:
        return sorted(self._workers)

    # ------------------------------------------------------------------
    # Recovery and state
    # ------------------------------------------------------------------

    def recover(self, session_factory) -> list[dict]:
        """Re-queue (or retire) every orphaned run. Delegates to the
        worker module's recovery with the fleet's lease timeout."""
        return recover_orphans(
            session_factory, lease_timeout_s=self.lease_timeout_s
        )

    def state(self, session_factory) -> dict:
        """Fleet and queue at a glance: who is running, what is waiting."""
        return {
            "controller": self.name,
            "profile": self.profile,
            "workers": self.worker_ids(),
            "lease_timeout_s": self.lease_timeout_s,
            "queue": queue_state(session_factory),
        }

    def shutdown(self) -> None:
        for worker_id in list(self._workers):
            self.remove_worker(worker_id)

    def __enter__(self) -> "Fleet":
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown()
