"""Budgets: computation as a scarce resource (S33).

Five kinds of compute, one ledger each:

- ``tokens`` — the model's input and output words, counted by the
  policy that calls it (the world cannot see a provider's bill);
- ``model_calls`` — how many times a mind may think at all;
- ``cpu_seconds`` — the wall-clock the simulation itself burns;
- ``actions`` — what an entity may do in the world;
- ``experiment`` — a study-wide ceiling shared by every agent, so a
  run cannot outspend its budget however many minds it spawns.

Each budget is a *remaining* ledger with an optional cap. Spending
that would cross a cap raises ``LimitExceeded`` — the caller decides
what that means (a rejected action, a silent skip, a stopped run).
An uncapped resource (``None``) is unlimited, which is what a world
without budgets means: the constraint is opt-in, per agent, per
experiment.

Budgets are checked at every seam that spends, and the *observation*
carries what remains — a mind that can see its budget can economise,
which is the whole point of making compute visible.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# The budget kinds the world knows, in the order they are reported.
# ``experiment`` is the run's shared ceiling: an agent never *has* one
# of its own, so only the other four may appear in a spawn rule.
KINDS = ("tokens", "model_calls", "cpu_seconds", "actions", "experiment")
AGENT_KINDS = ("tokens", "model_calls", "cpu_seconds", "actions")


class LimitExceeded(Exception):
    """A spend that would cross a configured cap.

    Carries the kind, the amount asked for, and what remained, so the
    rejection records truthfully what was refused.
    """

    def __init__(self, kind: str, amount: float, remaining: float) -> None:
        self.kind = kind
        self.amount = amount
        self.remaining = remaining
        super().__init__(
            f"budget {kind} exceeded: wanted {amount}, "
            f"{remaining} remaining"
        )


def _clean(value, kind: str) -> float | None:
    """Validate one budget value: a non-negative number, or None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"budget {kind} must be a number, got {value!r}")
    if value < 0:
        raise ValueError(f"budget {kind} cannot be negative, got {value!r}")
    return value


@dataclass
class Budget:
    """One agent's (or one experiment's) remaining compute."""

    limits: dict = field(default_factory=dict)  # kind -> cap (None = unlimited)
    spent: dict = field(default_factory=dict)  # kind -> total spent

    def __post_init__(self) -> None:
        for kind in KINDS:
            self.limits[kind] = _clean(self.limits.get(kind), kind)
            self.spent.setdefault(kind, 0)

    # --- spending ---

    def remaining(self, kind: str) -> float | None:
        """What is left; None when the kind is uncapped."""
        if kind not in KINDS:
            raise ValueError(f"unknown budget kind {kind!r}; expected one of {KINDS}")
        cap = self.limits[kind]
        if cap is None:
            return None
        return max(0, cap - self.spent[kind])

    def can_afford(self, kind: str, amount: float = 1) -> bool:
        cap = self.limits[kind]
        return cap is None or self.spent[kind] + amount <= cap

    def spend(self, kind: str, amount: float = 1) -> None:
        """Spend from a kind, refusing what would cross the cap.

        ``LimitExceeded`` carries the truth: nothing is deducted when
        a spend is refused — a budget that lies is worse than none.
        """
        if kind not in KINDS:
            raise ValueError(f"unknown budget kind {kind!r}; expected one of {KINDS}")
        amount = _clean(amount, kind)
        if amount is None:  # pragma: no cover - validation above rejects it
            raise ValueError("an amount is required")
        if not self.can_afford(kind, amount):
            raise LimitExceeded(kind, amount, self.remaining(kind) or 0)
        self.spent[kind] += amount

    # --- reporting ---

    def to_dict(self) -> dict:
        """The ledger as data: spent, capped, and what remains."""
        return {
            kind: {
                "spent": self.spent[kind],
                "cap": self.limits[kind],
                "remaining": self.remaining(kind),
            }
            for kind in KINDS
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Budget":
        data = data or {}
        limits = {kind: data.get(kind) for kind in KINDS}
        return cls(limits=limits)


@dataclass
class Clock:
    """Wall-clock accounting, measured only where it is spent (S33).

    ``cpu_seconds`` is real time in the simulation's own process: the
    clock is started per measured region and the elapsed seconds are
    charged to the budget that runs it. Never wall-clock by accident.
    """

    def __init__(self) -> None:
        self._started: float | None = None

    def since(self) -> float:
        return time.perf_counter() - self._started if self._started is not None else 0.0
