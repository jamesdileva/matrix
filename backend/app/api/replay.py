"""The time machine's routes (S37).

Read-only, all of it: the log is the source of truth, and a replay
route changes nothing. Terrain comes from the world's seed (the
world's generation is deterministic, so replaying a seed rebuilds the
ground the history walked on); everything else comes from the events.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.persistence.repositories import EventRepository
from app.simulation.events import EventTypes
from app.simulation.replay import EventReplay
from app.simulation.world import World

router = APIRouter(tags=["replay"])


def _replay(request: Request, world_id: int) -> tuple[EventReplay, dict]:
    """The world's replay, plus the shape its ground was generated from."""
    host = request.app.state.worlds.get(world_id)
    if host is None:
        raise HTTPException(status_code=404, detail=f"world {world_id} not found")
    session_factory = request.app.state.worlds.session_factory
    events = EventRepository(session_factory).load_for_replay(world_id)
    live = host.engine.world
    ground = World.generate(live.seed, live.width, live.height)
    terrain = [[cell.value for cell in row] for row in ground.terrain]
    return EventReplay(events), {
        "world_id": world_id,
        "seed": live.seed,
        "width": live.width,
        "height": live.height,
        "terrain": terrain,
    }


@router.get("/worlds/{world_id}/replay/timeline")
def get_timeline(world_id: int, request: Request) -> dict:
    """The log's shape: ticks covered, counts by type, generations seen."""
    replay, ground = _replay(request, world_id)
    return {"world_id": world_id, "timeline": replay.timeline()}


@router.get("/worlds/{world_id}/replay/state")
def get_state(
    world_id: int,
    request: Request,
    tick: int | None = Query(None, ge=0),
    event_id: int | None = Query(None, ge=0),
) -> dict:
    """The world reconstructed at `tick`, or immediately after one
    `event_id` — the time machine's jump.

    A birth-only lineage lives inside one tick, so an event address is
    the finer granularity when a tick cannot separate generations.
    Either way the snapshot matches the console's world shape, so the
    viewport renders a past moment exactly as it renders the live one.
    """
    replay, ground = _replay(request, world_id)
    if event_id is not None:
        state = replay.state_after(event_id)
    else:
        state = replay.state_at(tick or 0)
    snapshot = state.snapshot(
        world_id=world_id,
        seed=ground["seed"],
        width=ground["width"],
        height=ground["height"],
        terrain=ground["terrain"],
    )
    return snapshot


@router.get("/worlds/{world_id}/replay/events")
def get_events(
    world_id: int,
    request: Request,
    from_tick: int = Query(0, ge=0),
    to_tick: int | None = Query(None, ge=0),
    type: str | None = None,
    actor_id: int | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """Events between two ticks, filterable — inspecting the intermediate
    history between any two jumps."""
    replay, _ground = _replay(request, world_id)
    events = replay.events_between(from_tick, to_tick if to_tick is not None else from_tick)
    selected = [
        event
        for event in events
        if (type is None or event.type == type)
        and (actor_id is None or event.actor_id == actor_id)
    ]
    return {
        "world_id": world_id,
        "from_tick": from_tick,
        "to_tick": to_tick,
        "count": len(selected),
        "events": [event.to_dict() for event in selected[-limit:]],
    }


@router.get("/worlds/{world_id}/replay/diff")
def get_diff(world_id: int, request: Request, a: int = Query(..., ge=0), b: int = Query(..., ge=0)) -> dict:
    """The comparison view: what changed between two ticks."""
    replay, _ground = _replay(request, world_id)
    return {"world_id": world_id, "diff": replay.diff(a, b)}


@router.get("/worlds/{world_id}/replay/event/{event_id}")
def get_event(world_id: int, event_id: int, request: Request) -> dict:
    """One event by its per-world id — event jumping, one hop."""
    replay, _ground = _replay(request, world_id)
    event = next((e for e in replay.events if e.id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail=f"event {event_id} not in world {world_id}")
    return {"world_id": world_id, "event": event.to_dict()}


@router.get("/worlds/{world_id}/replay/culture")
def get_culture(world_id: int, request: Request, tick: int = Query(..., ge=0)) -> dict:
    """Who knew what, and what was said, as of one tick."""
    replay, _ground = _replay(request, world_id)
    state = replay.state_at(tick)
    return {
        "world_id": world_id,
        "tick": tick,
        "culture": {
            str(entity_id): entry for entity_id, entry in sorted(state.culture.items())
        },
    }
