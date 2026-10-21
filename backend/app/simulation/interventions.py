"""Human interventions (S45): measured changes to a living world.

The participant is no longer only a body in the grid. This module names
the ways an operator can change a world — give or take information, place
an object, assign a goal, join or leave a population — and records each
one with a baseline. The current world can later be compared with that
baseline, so an intervention has an outcome rather than only a story.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from app.simulation.events import EventTypes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.simulation.world import World


INTERVENTION_KINDS = (
    "provide_information",
    "remove_information",
    "introduce_object",
    "give_task",
    "join_population",
    "leave_population",
)

INTERVENTION_CATALOG = {
    "provide_information": {
        "name": "Provide information",
        "description": "Teach one agent facts it did not carry.",
        "parameters": ["agent_id", "facts"],
    },
    "remove_information": {
        "name": "Remove information",
        "description": "Take facts, recipes, or patterns away from one agent.",
        "parameters": ["agent_id", "facts"],
    },
    "introduce_object": {
        "name": "Introduce an object",
        "description": "Place an object on a free floor cell.",
        "parameters": ["object_type", "x", "y", "quantity", "properties"],
    },
    "give_task": {
        "name": "Give a task",
        "description": "Set the goal an agent carries into its next decisions.",
        "parameters": ["agent_id", "task"],
    },
    "join_population": {
        "name": "Join a population",
        "description": "Make the participant a member of an existing population.",
        "parameters": ["population_id"],
    },
    "leave_population": {
        "name": "Leave the population",
        "description": "End the participant's population membership.",
        "parameters": [],
    },
}

# Metrics every intervention is measured against. They are counts, so a
# delta is meaningful and comparable across worlds.
METRIC_KEYS = (
    "tick",
    "entities",
    "population",
    "objects",
    "knowledge_facts",
    "known_recipes",
    "known_patterns",
    "settlements",
    "games",
    "challenges_completed",
    "messages",
    "resources",
)


def intervention_catalog() -> dict:
    """The intervention shelf, in the same shape as the challenge shelf."""
    return {
        "kinds": [
            {"kind": kind, **copy.deepcopy(INTERVENTION_CATALOG[kind])}
            for kind in INTERVENTION_KINDS
        ],
        "metrics": list(METRIC_KEYS),
        "measurement": (
            "Each intervention records the world before it was applied; "
            "reading it later returns the current values and the delta."
        ),
    }


def world_metrics(world: "World", agents: Iterable[object] = ()) -> dict:
    """Counts that describe a world and its minds right now.

    `agents` is supplied by the host because an engine's Agent objects are
    not stored inside World; a World used on its own still measures its
    physical and social state.
    """
    alive = [
        agent
        for agent in agents
        if getattr(agent, "status", None) == "alive"
        and getattr(agent, "position", None) is not None
    ]
    return {
        "tick": world.tick,
        "entities": len(world._entities),
        "population": len(alive),
        "objects": sum(1 for obj in world.objects if obj.position is not None),
        "knowledge_facts": sum(
            len(getattr(agent, "knowledge", ()) or ()) for agent in alive
        ),
        "known_recipes": sum(
            len(world.known_recipes(agent.agent_id)) for agent in alive
        ),
        "known_patterns": sum(
            len(world.known_patterns(agent.agent_id)) for agent in alive
        ),
        "settlements": len(world.settlements),
        "games": len(world.games),
        "challenges_completed": sum(
            1 for challenge in world.challenges if challenge.status == "completed"
        ),
        "messages": sum(
            1 for event in world.events if event.type == EventTypes.SPEECH
        ),
        "resources": sum(
            sum(ledger.values()) for ledger in world._resources.values()
        ),
    }


def metric_delta(before: dict, current: dict) -> dict:
    """Numeric change between two metric snapshots."""
    return {
        key: int(current.get(key, 0)) - int(before.get(key, 0))
        for key in METRIC_KEYS
    }


@dataclass
class Intervention:
    """One measured human change to a world."""

    id: int
    kind: str
    tick: int
    target: int | None
    details: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    status: str = "applied"

    def __post_init__(self) -> None:
        if self.kind not in INTERVENTION_KINDS:
            raise ValueError(f"unknown intervention kind {self.kind!r}")

    def to_dict(self, current: dict | None = None) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "tick": self.tick,
            "target": self.target,
            "details": copy.deepcopy(self.details),
            "baseline": dict(self.baseline),
            "status": self.status,
        }
        if current is not None:
            data["current"] = dict(current)
            data["delta"] = metric_delta(self.baseline, current)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Intervention":
        return cls(
            id=int(data["id"]),
            kind=str(data["kind"]),
            tick=int(data.get("tick") or 0),
            target=(
                int(data["target"]) if data.get("target") is not None else None
            ),
            details=copy.deepcopy(data.get("details") or {}),
            baseline=dict(data.get("baseline") or {}),
            status=str(data.get("status") or "applied"),
        )
