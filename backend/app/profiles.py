"""Hardware profiles: named execution environments (S49).

A profile declares how an experiment *executes* — how many claim loops
a worker runs, how many worlds a study may run at once — and never what
an experiment *means*. Determinism guarantees the rest: the same
configuration under Tiny and Cloud produces identical outcome metrics,
so the outcome comparison across profiles is an equality check, while
the recorded runtimes (duration, throughput) are the comparable
performance story.

A profile cannot make a laptop a GPU. What it can do is name the
environment a run happened in, cap its concurrency, and put the run's
wall-clock facts next to its results.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PROFILE = "desktop"


@dataclass(frozen=True)
class Profile:
    name: str
    workers: int  # concurrent claim loops a worker runs
    max_parallel_worlds: int  # worlds a study may run at once
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "workers": self.workers,
            "max_parallel_worlds": self.max_parallel_worlds,
            "description": self.description,
        }


HARDWARE_PROFILES: dict[str, Profile] = {
    "tiny": Profile(
        "tiny", 1, 2,
        "one claim loop, two worlds at a time: a small machine sharing politely",
    ),
    "desktop": Profile(
        "desktop", 2, 4,
        "the default workstation: two claim loops, four worlds at a time",
    ),
    "gpu": Profile(
        "gpu", 2, 4,
        "the workstation that hosts model minds: same shape as desktop, "
        "for runs whose budgets are spent in tokens",
    ),
    "cloud": Profile(
        "cloud", 8, 8,
        "generous concurrency: many loops, many worlds, ceilings wide open",
    ),
}


def get_profile(name: str | None) -> Profile:
    """Resolve a profile name, defaulting to Desktop. Unknown names raise."""
    if name is None:
        name = DEFAULT_PROFILE
    if name not in HARDWARE_PROFILES:
        raise ValueError(
            f"unknown hardware profile {name!r}; expected one of {sorted(HARDWARE_PROFILES)}"
        )
    return HARDWARE_PROFILES[name]


def _outcome_fingerprint(study: dict) -> dict:
    """A study minus its row identity and its runtime — the part two
    profiles must produce identically."""
    body = dict(study or {})
    body.pop("experiment_id", None)
    body.pop("name", None)
    body.pop("runtime", None)
    for run in body.get("runs", []):
        run.pop("experiment_id", None)
    return body


def compare_across_profiles(first: dict, second: dict) -> dict:
    """Two studies of the same configuration, run under different
    profiles. Outcome metrics must match exactly; the runtimes are the
    performance comparison."""
    runtime_a = first.get("runtime") or {}
    runtime_b = second.get("runtime") or {}
    return {
        "outcomes_identical": _outcome_fingerprint(first) == _outcome_fingerprint(second),
        "profiles": [runtime_a.get("profile"), runtime_b.get("profile")],
        "runtime": {"first": runtime_a, "second": runtime_b},
    }
