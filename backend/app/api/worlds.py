"""The Simulation API: create, watch, and control live worlds.

Routes only orchestrate — world truth lives in the engine, and every
route reads through the `WorldRegistry` on `app.state.worlds`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.host import BRAINS_MODEL, BRAINS_SCRIPTED, WorldHost

router = APIRouter(tags=["worlds"])


class CreateWorldRequest(BaseModel):
    seed: str = "void"
    width: int = Field(default=32, ge=8, le=256)
    height: int = Field(default=32, ge=8, le=256)
    agents: int = Field(default=3, ge=0, le=64)
    tick_rate: float = Field(default=6.0, gt=0, le=120)
    autostart: bool = True
    # S08: which minds inhabit the world. "model" is an explicit opt-in —
    # a configured provider alone never starts a model world.
    brains: str = BRAINS_SCRIPTED


def _host(request: Request, world_id: int) -> WorldHost:
    host = request.app.state.worlds.get(world_id)
    if host is None:
        raise HTTPException(status_code=404, detail=f"world {world_id} not found")
    return host


def _state(host: WorldHost) -> dict:
    snapshot = host.engine.world.snapshot()
    snapshot["id"] = host.world_id
    snapshot["paused"] = host.paused
    snapshot["agent_count"] = len(host.engine.agents)
    snapshot["brains"] = host.brains
    snapshot["provider"] = (
        {"provider": host.provider.name, "model": getattr(host.provider, "model", None)}
        if host.provider is not None
        else None
    )
    return snapshot


@router.post("/worlds", status_code=201)
async def create_world(payload: CreateWorldRequest, request: Request) -> dict:
    # async: autostart must call asyncio.create_task, which needs the
    # event loop — a sync route would run in a worker thread without one.
    try:
        host = request.app.state.worlds.create(
            seed=payload.seed,
            width=payload.width,
            height=payload.height,
            agents=payload.agents,
            tps=payload.tick_rate,
            autostart=payload.autostart,
            brains=payload.brains,
        )
    except ValueError as exc:
        # Unknown brains, or a misconfigured model provider.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _state(host)


@router.get("/worlds")
def list_worlds(request: Request) -> dict:
    worlds = [
        {"id": h.world_id, "seed": h.engine.world.seed, "tick": h.engine.world.tick,
         "paused": h.paused, "agents": len(h.engine.agents), "brains": h.brains}
        for h in request.app.state.worlds.all()
    ]
    return {"worlds": worlds}


@router.get("/worlds/{world_id}")
def get_world(world_id: int, request: Request) -> dict:
    return _state(_host(request, world_id))


@router.post("/worlds/{world_id}/step")
async def step_world(world_id: int, request: Request) -> dict:
    # async: model worlds await their provider inside the step.
    host = _host(request, world_id)
    await host.advance_once()
    return _state(host)


@router.post("/worlds/{world_id}/pause")
def pause_world(world_id: int, request: Request) -> dict:
    host = _host(request, world_id)
    host.pause()
    return {"id": host.world_id, "paused": True}


@router.post("/worlds/{world_id}/resume")
def resume_world(world_id: int, request: Request) -> dict:
    host = _host(request, world_id)
    host.resume()
    return {"id": host.world_id, "paused": False}


@router.get("/worlds/{world_id}/events")
def get_events(
    world_id: int,
    request: Request,
    since_id: int = 0,
    limit: int = 100,
) -> dict:
    host = _host(request, world_id)
    limit = max(1, min(limit, 1000))
    events = [e.to_dict() for e in host.engine.world.events if e.id > since_id]
    return {"world_id": world_id, "events": events[-limit:]}


@router.delete("/worlds/{world_id}")
async def delete_world(world_id: int, request: Request) -> dict:
    host = _host(request, world_id)
    await host.stop()
    request.app.state.worlds.remove(world_id)
    return {"id": world_id, "stopped": True}
