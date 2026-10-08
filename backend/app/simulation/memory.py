"""Short memory: an agent's recent history.

Cognition (S08) needs more than the current tick: what the agent just
tried, whether it worked, and what it was trying to achieve. That is
this module — a small, bounded, JSON-serializable ring of outcomes.

Deliberately *not* long-term knowledge: inheritance and persistent
memory are lineage/experiment concerns (S09+). The bound is what keeps
model requests cheap and behavior explainable: only the most recent
entries are ever seen.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field

DEFAULT_MEMORY_LIMIT = 16


@dataclass
class AgentMemory:
    """Bounded FIFO of recent action outcomes, oldest first."""

    limit: int = DEFAULT_MEMORY_LIMIT
    _entries: deque = field(default_factory=deque, repr=False)

    def remember(self, entry: dict) -> None:
        """Record one entry, evicting the oldest past the limit.

        Entries are deep-copied on the way in and out: the engine hands
        in action payloads it may still reference, and observers
        (observations, logged events) must never alias live memory.
        """
        self._entries.append(copy.deepcopy(entry))
        while len(self._entries) > self.limit:
            self._entries.popleft()

    def remember_action(
        self,
        *,
        tick: int,
        action: dict,
        ok: bool,
        reason: str | None,
        goal: str | None,
    ) -> None:
        """Record the outcome of one attempted action."""
        self.remember(
            {
                "tick": tick,
                "action": dict(action),
                "ok": ok,
                "reason": reason,
                "goal": goal,
            }
        )

    def recent(self, count: int | None = None) -> list[dict]:
        """The most recent entries (newest last); a copy, safe to mutate."""
        entries = [copy.deepcopy(entry) for entry in self._entries]
        return entries if count is None else entries[-count:]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
