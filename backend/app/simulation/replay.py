"""Replay: the world as history, explorable at any tick (S37).

The timeline *is* the world's memory: every mutation the engine made
was recorded as an event, payload and all. The replay engine reads
that log back and reconstructs state at an arbitrary tick — entities
where they stood, objects where they lay, ledgers as they stood,
culture as it travelled. Nothing here trusts the live world; the log
is the source of truth, which is what makes it a time machine rather
than a cache.

Fidelity is reported, not assumed. Events whose effects the engine
knows how to re-apply are `applied`; the rest are `unapplied`, counted
by type — a replay that silently skipped half the log would be a lie
with a nice UI, so the count is always in the answer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.simulation.actions import DIRECTIONS
from app.simulation.events import Event, EventTypes

# The payload keys each replayed event carries, documented once.
_MOVE = "to"


@dataclass
class ReplayState:
    """The world, reconstructed up to one tick."""

    tick: int = 0
    entities: dict[int, dict] = field(default_factory=dict)
    objects: dict[int, dict] = field(default_factory=dict)
    inventories: dict[int, list[int]] = field(default_factory=dict)
    resources: dict[int, dict] = field(default_factory=dict)
    culture: dict[int, dict] = field(default_factory=dict)
    applied: int = 0
    unapplied: Counter = field(default_factory=Counter)
    events_seen: int = 0

    # --- the event handlers ---

    def apply(self, event: Event) -> None:
        self.events_seen += 1
        handler = _HANDLERS.get(event.type)
        if handler is None:
            self.unapplied[event.type] += 1
            return
        handler(self, event)
        self.applied += 1

    def snapshot(
        self,
        *,
        world_id: int,
        seed: str,
        width: int,
        height: int,
        terrain: list[list[str]],
    ) -> dict:
        """The reconstructed state as the console's world shape."""
        return {
            "id": world_id,
            "seed": seed,
            "width": width,
            "height": height,
            "tick": self.tick,
            "terrain": ["".join(row) for row in terrain],
            "objects": [
                {
                    "id": object_id,
                    "type": obj["type"],
                    "position": obj["position"],
                }
                for object_id, obj in sorted(self.objects.items())
                if obj["position"] is not None
            ],
            "entities": {
                str(entity_id): {"x": pos["x"], "y": pos["y"]}
                for entity_id, pos in sorted(self.entities.items())
            },
            "agent_count": len(self.entities),
            "paused": True,  # a time machine is never running
            "brains": "replay",
            "provider": None,
            "replay": {
                "applied": self.applied,
                "unapplied": dict(self.unapplied),
                "events_seen": self.events_seen,
                "inventories": {
                    str(entity_id): list(items)
                    for entity_id, items in sorted(self.inventories.items())
                },
                "resources": {
                    str(entity_id): dict(ledger)
                    for entity_id, ledger in sorted(self.resources.items())
                },
                "culture": {
                    str(entity_id): value for entity_id, value in sorted(self.culture.items())
                },
            },
        }


# --- the handlers, one per replayed event type ---


def _on_entity_added(state: ReplayState, event: Event) -> None:
    position = event.payload.get("position")
    if position and event.actor_id is not None:
        state.entities[event.actor_id] = dict(position)


def _on_entity_removed(state: ReplayState, event: Event) -> None:
    if event.actor_id is not None:
        state.entities.pop(event.actor_id, None)
        state.inventories.pop(event.actor_id, None)
        state.culture.pop(event.actor_id, None)


def _on_action(state: ReplayState, event: Event) -> None:
    """One executed action, re-applied from its payload."""
    action = event.payload.get("action")
    if not isinstance(action, dict):
        return
    verb = action.get("action")
    actor = event.actor_id
    if actor is None:
        return
    if verb == "move":
        target = event.payload.get(_MOVE)
        if target:
            state.entities[actor] = dict(target)
    elif verb == "pick_up":
        object_id = event.payload.get("object_id")
        if isinstance(object_id, int):
            obj = state.objects.get(object_id)
            if obj is not None:
                obj["position"] = None
                obj["carried_by"] = actor
                state.inventories.setdefault(actor, []).append(object_id)
    elif verb in ("drop", "place"):
        object_id = event.payload.get("object_id")
        target = event.payload.get("to")
        if isinstance(object_id, int) and target:
            obj = state.objects.get(object_id)
            if obj is not None:
                obj["position"] = dict(target)
                obj["carried_by"] = None
                if object_id in state.inventories.get(actor, []):
                    state.inventories[actor].remove(object_id)
    elif verb == "gather":
        resource = event.payload.get("resource")
        amount = event.payload.get("amount")
        if isinstance(resource, str) and isinstance(amount, int):
            ledger = state.resources.setdefault(actor, {})
            ledger[resource] = ledger.get(resource, 0) + amount
    elif verb == "build":
        object_id = event.payload.get("object_id")
        position = event.payload.get("position")
        block = event.payload.get("block")
        if isinstance(object_id, int) and position and isinstance(block, str):
            state.objects[object_id] = {
                "type": block,
                "position": dict(position),
                "carried_by": None,
            }
        # The materials the build spent ride the event, so the ledger
        # replays too.
        cost = event.payload.get("cost")
        if isinstance(cost, dict):
            ledger = state.resources.setdefault(actor, {})
            for kind, amount in cost.items():
                if isinstance(amount, int):
                    ledger[kind] = max(0, ledger.get(kind, 0) - amount)
    elif verb == "remove":
        object_id = event.payload.get("object_id")
        if isinstance(object_id, int):
            state.objects.pop(object_id, None)
    elif verb in ("give", "take", "trade"):
        _replay_transfer(state, event, actor)
    elif verb in ("say", "tell", "announce", "broadcast"):
        message = event.payload.get("message")
        if isinstance(message, str):
            state.culture.setdefault(actor, {}).setdefault("messages", []).append(message)


def _replay_transfer(state: ReplayState, event: Event, actor: int) -> None:
    """A transfer's two legs, re-applied to both inventories."""
    kind = event.payload.get("kind")
    if kind == "object":
        object_id = event.payload.get("object_id")
        source, target = event.payload.get("from"), event.payload.get("to")
        if isinstance(object_id, int):
            if source in state.inventories and object_id in state.inventories[source]:
                state.inventories[source].remove(object_id)
            if target is not None:
                state.inventories.setdefault(target, []).append(object_id)
                obj = state.objects.get(object_id)
                if obj is not None:
                    obj["carried_by"] = target
    elif kind == "resource":
        resource = event.payload.get("resource")
        amount = event.payload.get("amount")
        source, target = event.payload.get("from"), event.payload.get("to")
        if isinstance(resource, str) and isinstance(amount, int):
            if source is not None:
                ledger = state.resources.setdefault(source, {})
                ledger[resource] = max(0, ledger.get(resource, 0) - amount)
            if target is not None:
                ledger = state.resources.setdefault(target, {})
                ledger[resource] = ledger.get(resource, 0) + amount


def _on_object_created(state: ReplayState, event: Event) -> None:
    object_id = event.target_id
    position = event.payload.get("position")
    if object_id is None:
        return
    if event.payload.get("carried"):
        # A crafted thing: carried by its maker, off the grid.
        state.objects[object_id] = {
            "type": event.payload.get("type", "?"),
            "position": None,
            "carried_by": event.actor_id,
        }
        if event.actor_id is not None:
            state.inventories.setdefault(event.actor_id, []).append(object_id)
        return
    state.objects[object_id] = {
        "type": event.payload.get("type", "?"),
        "position": dict(position) if position else None,
        "carried_by": None,
    }


def _on_object_depleted(state: ReplayState, event: Event) -> None:
    object_id = event.target_id
    if object_id is None:
        return
    obj = state.objects.pop(object_id, None)
    if obj and obj.get("carried_by") is not None and object_id in state.inventories.get(
        obj["carried_by"], []
    ):
        state.inventories[obj["carried_by"]].remove(object_id)


def _on_agent_born(state: ReplayState, event: Event) -> None:
    """A birth: a new entity, and the culture it was handed."""
    child = event.target_id
    position = event.payload.get("position")
    if child is None:
        return
    if position:
        state.entities[child] = dict(position)
    inheritance = event.payload.get("inheritance") or {}
    knowledge = inheritance.get("knowledge")
    if isinstance(knowledge, list):
        state.culture[child] = {
            "knowledge": [str(fact) for fact in knowledge],
            "generation": event.payload.get("generation"),
            "parent": event.actor_id,
        }


_HANDLERS = {
    EventTypes.ENTITY_ADDED: _on_entity_added,
    EventTypes.ENTITY_REMOVED: _on_entity_removed,
    EventTypes.ACTION_EXECUTED: _on_action,
    EventTypes.OBJECT_CREATED: _on_object_created,
    EventTypes.OBJECT_DEPLETED: _on_object_depleted,
    EventTypes.AGENT_BORN: _on_agent_born,
}


class EventReplay:
    """One world's log, replayed to any tick."""

    def __init__(self, events: list[Event]) -> None:
        self.events = sorted(events, key=lambda e: (e.tick, e.id))
        self._cache: dict[int, ReplayState] = {}

    def state_at(self, tick: int) -> ReplayState:
        """The reconstruction at `tick` (cached across repeated jumps)."""
        if tick in self._cache:
            return self._cache[tick]
        state = ReplayState()
        for event in self.events:
            if event.tick > tick:
                break
            state.apply(event)
        state.tick = tick
        self._cache[tick] = state
        return state

    def state_after(self, event_id: int) -> ReplayState:
        """The reconstruction immediately after one event — the finest
        jump the timeline offers.

        Some histories (a birth-only lineage) happen entirely within
        one tick; for those, a tick address cannot separate
        generations, but an event address always can.
        """
        key = f"event:{event_id}"
        if key in self._cache:
            return self._cache[key]
        state = ReplayState()
        for event in self.events:
            if event.id > event_id:
                break
            state.apply(event)
        state.tick = event.tick if event else state.tick
        self._cache[key] = state
        return state

    def events_between(self, first: int, second: int) -> list[Event]:
        return [e for e in self.events if first <= e.tick <= second]

    def timeline(self) -> dict:
        """The log's shape: ticks covered, counts by type, who appeared."""
        counts = Counter(e.type for e in self.events)
        births = [e for e in self.events if e.type == EventTypes.AGENT_BORN]
        return {
            "events": len(self.events),
            "first_tick": self.events[0].tick if self.events else 0,
            "last_tick": self.events[-1].tick if self.events else 0,
            "by_type": dict(counts.most_common()),
            "births": len(births),
            "generations": max((e.payload.get("generation", 0) for e in births), default=0),
            "entities_seen": len({e.actor_id for e in self.events if e.actor_id is not None}),
        }

    def diff(self, first: int, second: int) -> dict:
        """What changed between two ticks, in the log's own terms."""
        before, after = self.state_at(first), self.state_at(second)
        return {
            "from_tick": first,
            "to_tick": second,
            "entities_moved": {
                str(entity_id): {
                    "from": before.entities.get(entity_id),
                    "to": after.entities.get(entity_id),
                }
                for entity_id in sorted(
                    set(before.entities) | set(after.entities)
                )
                if before.entities.get(entity_id) != after.entities.get(entity_id)
            },
            "entities_added": sorted(set(after.entities) - set(before.entities)),
            "entities_removed": sorted(set(before.entities) - set(after.entities)),
            "objects_added": sorted(set(after.objects) - set(before.objects)),
            "objects_removed": sorted(set(before.objects) - set(after.objects)),
            "resources_changed": {
                str(entity_id): {
                    kind: {
                        "from": before.resources.get(entity_id, {}).get(kind, 0),
                        "to": after.resources.get(entity_id, {}).get(kind, 0),
                    }
                    for kind in sorted(
                        set(before.resources.get(entity_id, {}))
                        | set(after.resources.get(entity_id, {}))
                    )
                    if before.resources.get(entity_id, {}).get(kind, 0)
                    != after.resources.get(entity_id, {}).get(kind, 0)
                }
                for entity_id in sorted(
                    set(before.resources) | set(after.resources)
                )
            },
            "culture_changed": {
                str(entity_id): {
                    "from": (before.culture.get(entity_id) or {}).get("knowledge"),
                    "to": (after.culture.get(entity_id) or {}).get("knowledge"),
                }
                for entity_id in sorted(set(before.culture) | set(after.culture))
                if (before.culture.get(entity_id) or {}).get("knowledge")
                != (after.culture.get(entity_id) or {}).get("knowledge")
            },
        }
