"""The inheritance package: what survives from parent to child (S10).

Four parts, per the roadmap: traits, knowledge, message, cultural
artifacts. The package is authored by the parent as *intent* — a
decision's ``inheritance`` field — and travels through
``Engine.create_child`` to the child.

Two rules the package exists to enforce (roadmap S10 verification):

- the child receives the parent's *intended* inheritance — nothing is
  copied behind the parent's back;
- uninherited memory does not magically appear — a parent's own state
  (knowledge, memory) is never transmitted unless the package carries
  it.

Transfers are deep copies: after a birth, parent and child states are
independent, and the package recorded on the AGENT_BORN event can
never alias a later mutation of either.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

PARTS = ("traits", "knowledge", "message", "cultural_artifacts")


@dataclass(frozen=True)
class InheritancePackage:
    """A parent's intended inheritance, normalized and validated."""

    traits: dict = field(default_factory=dict)
    knowledge: tuple = ()
    message: str | None = None
    cultural_artifacts: tuple = ()

    @classmethod
    def from_dict(cls, data: dict | None) -> "InheritancePackage":
        """Tolerant parse: wrong-typed parts are dropped, never fatal.

        Consistent with the decision contract's optional fields —
        annotation is dropped, the birth still happens.
        """
        data = data or {}
        if not isinstance(data, dict):
            return cls()
        traits = data.get("traits")
        knowledge = data.get("knowledge")
        artifacts = data.get("cultural_artifacts")
        message = data.get("message")
        return cls(
            traits=copy.deepcopy(traits) if isinstance(traits, dict) else {},
            knowledge=tuple(copy.deepcopy(knowledge)) if isinstance(knowledge, list) else (),
            message=message if isinstance(message, str) else None,
            cultural_artifacts=(
                tuple(copy.deepcopy(artifacts)) if isinstance(artifacts, list) else ()
            ),
        )

    def as_dict(self) -> dict:
        """JSON-safe form for events, API responses and the database."""
        return {
            "traits": copy.deepcopy(self.traits),
            "knowledge": list(self.knowledge),
            "message": self.message,
            "cultural_artifacts": list(self.cultural_artifacts),
        }
