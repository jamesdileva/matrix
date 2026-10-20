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
    # S28: networks. A named letter, a group announcement and a
    # broadcast are facts too — each with its own delivery set.
    DIRECT = "DIRECT"
    ANNOUNCE = "ANNOUNCE"
    BROADCAST = "BROADCAST"
    # S29: technology. A discovery, a crafting and an invention are
    # facts too — culture is made of them.
    INVENTION = "INVENTION"
    CRAFT = "CRAFT"
    # S30: settlements. A community founded, joined, grown, banked
    # into, paved and claimed is a fact too.
    SETTLEMENT_FOUNDED = "SETTLEMENT_FOUNDED"
    SETTLEMENT_JOINED = "SETTLEMENT_JOINED"
    SETTLEMENT_GROWN = "SETTLEMENT_GROWN"
    SETTLEMENT_STORAGE = "SETTLEMENT_STORAGE"
    ROAD_LAID = "ROAD_LAID"
    ZONE_CLAIMED = "ZONE_CLAIMED"
    # S31: games. A proposed game, a played move and a finished game
    # are facts too — the table's history is on the timeline.
    GAME_PROPOSED = "GAME_PROPOSED"
    GAME_STARTED = "GAME_STARTED"
    GAME_MOVE = "GAME_MOVE"
    GAME_OVER = "GAME_OVER"
    # S33: compute. A mind that could not afford to think is a fact
    # too — scarcity is part of the history.
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    # S27: populations. A group coming to be — founded, or a new
    # member arriving under its spawn rule — is a fact too.
    POPULATION_SPAWN = "POPULATION_SPAWN"
    # S41: genetics. The genome a child inherited, and the mutations that
    # changed it, are facts too — a lineage's drift is on the timeline.
    GENES_INHERITED = "GENES_INHERITED"
    # S42: language. A named concept and a borrowed word are facts too —
    # a vocabulary's growth is a timeline, not an assumption.
    WORD_INVENTED = "WORD_INVENTED"
    WORD_ADOPTED = "WORD_ADOPTED"
    # S43: ecosystem. Life and weather change on their own, within caps;
    # the timeline records the changes a reader would want to explain.
    ECOSYSTEM_SEEDED = "ECOSYSTEM_SEEDED"
    SEASON_CHANGED = "SEASON_CHANGED"
    WEATHER_CHANGED = "WEATHER_CHANGED"
    ANIMAL_BORN = "ANIMAL_BORN"
    ANIMAL_DIED = "ANIMAL_DIED"
    # S44: civilization challenges. A world can be asked to do something
    # measurable; the timeline records the ask and the verdict.
    CHALLENGE_STARTED = "CHALLENGE_STARTED"
    CHALLENGE_COMPLETED = "CHALLENGE_COMPLETED"
    CHALLENGE_FAILED = "CHALLENGE_FAILED"


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
