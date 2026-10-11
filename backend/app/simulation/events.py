"""The platform event model.

Every important state transition becomes an Event. Events are recorded
per-world with a tick and a per-world sequence id — the timeline is
simulation-relative by design. Wall-clock timestamps are deliberately NOT
part of engine events: they are metadata the persistence layer adds on
insert, because the engine must stay deterministic (same seed -> same
events, always).

Vocabulary is open-ended: new event types arrive with the features that
produce them. The constants here are the ones the core engine emits.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class EventTypes:
    WORLD_SEEDED = "WORLD_SEEDED"
    OBJECT_CREATED = "OBJECT_CREATED"
    OBJECT_DEPLETED = "OBJECT_DEPLETED"
    ENTITY_ADDED = "ENTITY_ADDED"
    ENTITY_REMOVED = "ENTITY_REMOVED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_REJECTED = "ACTION_REJECTED"
    # S08: model minds speak through the same timeline as everything
    # else, so a decision, its failure, and an utterance are all
    # replayable facts about the world.
    MODEL_DECISION = "MODEL_DECISION"
    MODEL_ERROR = "MODEL_ERROR"
    AGENT_MESSAGE = "AGENT_MESSAGE"
    # S09: lineage. Parent, child and generation are one replayable
    # fact about the world, same as everything else.
    AGENT_BORN = "AGENT_BORN"
    # S16: culture. A produced artifact is a replayable fact too.
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    # S18: building. A structure is a replayable fact too.
    STRUCTURE_CREATED = "STRUCTURE_CREATED"
    # S21: speech. Something said aloud, by anyone, is a fact too.
    SPEECH = "SPEECH"
    # S22: social facts. Transfers between inventories and following.
    TRANSFER = "TRANSFER"
    FOLLOW = "FOLLOW"
    # S23: the escape. Leaving the sandbox is a fact too.
    ESCAPED = "ESCAPED"
    # S25: cooperation. A door opened by joint occupancy is a fact too.
    DOOR_OPENED = "DOOR_OPENED"
    # S27: populations. A group coming to be — founded, or a new
    # member arriving under its spawn rule — is a fact too.
    POPULATION_SPAWN = "POPULATION_SPAWN"


@dataclass(frozen=True)
class Event:
    id: int  # per-world sequence, 1-based
    tick: int
    type: str
    actor_id: int | None = None
    target_id: int | None = None
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tick": self.tick,
            "type": self.type,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            id=data["id"],
            tick=data["tick"],
            type=data["type"],
            actor_id=data.get("actor_id"),
            target_id=data.get("target_id"),
            payload=data.get("payload") or {},
        )
