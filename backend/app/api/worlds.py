"""The Simulation API: create, watch, and control live worlds.

Routes only orchestrate — world truth lives in the engine, and every
route reads through the `WorldRegistry` on `app.state.worlds`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.experiments.lineage import generation_metrics as _generation_metrics
from app.experiments.lineage import tokens as _tokens
from app.host import BRAINS_MODEL, BRAINS_SCRIPTED, WorldHost
from app.simulation.errors import BirthError
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy

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


class BirthRequest(BaseModel):
    parent_id: int
    # S10: the four-part package the parent intends to pass on. When
    # omitted, the parent's pending intent (declared by its last
    # decision) is used.
    inheritance: dict | None = None


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


@router.get("/worlds/{world_id}/agents")
def list_agents(world_id: int, request: Request) -> dict:
    """S13: the world's live population.

    Identity, lineage and status straight from the engine — the
    dashboard's population stats panel (generation, active agents)
    reads this. Detail like memory and knowledge are the agent
    inspector's (S14).
    """
    host = _host(request, world_id)
    agents = [
        {
            "id": agent.agent_id,
            "generation": agent.generation,
            "parent_id": agent.parent_id,
            "population_id": agent.population_id,
            "status": agent.status,
            "position": agent.position.to_dict() if agent.position else None,
            "goal": agent.goal,
            "policy": "model" if hasattr(agent.policy, "refresh") else "scripted",
            "knowledge": len(agent.knowledge),
        }
        for agent in host.engine.agents
    ]
    return {"world_id": world_id, "agents": agents}


@router.get("/worlds/{world_id}/agents/{agent_id}")
def get_agent(world_id: int, agent_id: int, request: Request) -> dict:
    """S14: one organism, examined — the agent inspector's feed.

    Identity, lineage in both directions (parent and children), short
    memory, the inherited package, the last action with its outcome,
    and compute state (decisions this agent made in the retained
    timeline, plus the provider envelope it calls through). Budget
    *enforcement* is the cognition scheduler's job (guide §25); this
    reports what is configured and what was spent.
    """
    host = _host(request, world_id)
    agent = next((a for a in host.engine.agents if a.agent_id == agent_id), None)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not in world {world_id}")

    response = getattr(agent.policy, "last_response", None)
    model_calls = sum(
        1
        for event in host.engine.world.events
        if event.type == EventTypes.MODEL_DECISION and event.actor_id == agent.agent_id
    )
    memory = agent.memory.recent()
    children = [a.agent_id for a in host.engine.agents if a.parent_id == agent.agent_id]

    return {
        "id": agent.agent_id,
        "status": agent.status,
        "position": agent.position.to_dict() if agent.position else None,
        "goal": agent.goal,
        "generation": agent.generation,
        "parent_id": agent.parent_id,
        "children": children,
        "population_id": agent.population_id,
        "policy": "model" if hasattr(agent.policy, "refresh") else "scripted",
        "provider": {
            "provider": getattr(response, "provider", None) if response is not None else None,
            "model": getattr(response, "model", None) if response is not None else None,
        },
        "compute": {
            "model_calls": model_calls,  # within the retained event window
            "envelope": {
                "temperature": settings.model_temperature,
                "max_tokens": settings.model_max_tokens,
                "timeout_seconds": settings.model_timeout_s,
            },
        },
        "last_action": (
            {
                "tick": memory[-1]["tick"],
                "action": memory[-1]["action"],
                "ok": memory[-1]["ok"],
                "reason": memory[-1]["reason"],
            }
            if memory
            else None
        ),
        "memory": memory,
        "inheritance": {
            "traits": agent.traits,
            "knowledge": agent.knowledge,
            "cultural_artifacts": agent.cultural_artifacts,
        },
    }


@router.get("/worlds/{world_id}/agents/{agent_id}/lineage")
def get_agent_lineage(world_id: int, agent_id: int, request: Request) -> dict:
    """S15: this agent's ancestry, founder first — the lineage explorer's feed.

    Each chain member carries its state, and its *drift* against the
    lineage's originals — the earliest knowledge in the chain —
    classified by the same rules the S11 experiment measures with
    (retained / lost / altered / new + similarity).
    """
    host = _host(request, world_id)
    agent = next((a for a in host.engine.agents if a.agent_id == agent_id), None)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not in world {world_id}")

    chain = host.engine.ancestors(agent.agent_id)  # founder -> selected agent
    # The lineage's originals: the earliest knowledge in the chain — the
    # founder's set when the founder carries one (the experiment's
    # shape), otherwise the first generation that did (live worlds'
    # founders start empty and receive the set with their first child).
    originals = next((list(m.knowledge) for m in chain if m.knowledge), [])
    original_tokens = [_tokens(fact) for fact in originals]

    members = []
    for member in chain:
        message = None
        for entry in member.memory.recent():
            if entry.get("action", {}).get("kind") == "inheritance":
                message = entry.get("reason")
        members.append(
            {
                "id": member.agent_id,
                "generation": member.generation,
                "parent_id": member.parent_id,
                "children": [a.agent_id for a in host.engine.agents if a.parent_id == member.agent_id],
                "position": member.position.to_dict() if member.position else None,
                "policy": "model" if hasattr(member.policy, "refresh") else "scripted",
                "goal": member.goal,
                "status": member.status,
                "knowledge_count": len(member.knowledge),
                "knowledge": list(member.knowledge),
                "traits": member.traits,
                "artifacts_count": len(member.cultural_artifacts),
                "inheritance_message": message,
                "drift": _generation_metrics(
                    member.generation,
                    member.knowledge,
                    None,
                    originals,
                    original_tokens,
                ),
            }
        )
    return {"world_id": world_id, "agent_id": agent.agent_id, "chain": members}


@router.post("/worlds/{world_id}/births", status_code=201)
def create_birth(world_id: int, payload: BirthRequest, request: Request) -> dict:
    """S09: one agent reproduces.

    The child of a model world gets a fresh ModelPolicy on the world's
    provider; the child of a scripted world gets the default scripted
    mind. Placement, lineage and the AGENT_BORN event are the engine's
    job (Engine.create_child).
    """
    host = _host(request, world_id)
    policy = ModelPolicy(host.provider) if host.provider is not None else None
    try:
        child = host.engine.create_child(
            payload.parent_id, policy=policy, inheritance=payload.inheritance
        )
    except ValueError as exc:  # unknown parent
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BirthError as exc:  # no room for the child
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    born = next(
        e
        for e in reversed(host.engine.world.events)
        if e.type == EventTypes.AGENT_BORN and e.target_id == child.agent_id
    )
    return {
        "id": child.agent_id,
        "parent_id": child.parent_id,
        "generation": child.generation,
        "population_id": child.population_id,
        "position": child.position.to_dict(),
        "inheritance": born.payload["inheritance"],
    }
