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
from app.host import (
    BRAINS_MODEL,
    BRAINS_SCRIPTED,
    PARTICIPANT_ENTITY_ID,
    WorldHost,
)
from app.simulation.errors import BirthError
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.population import PopulationManager, SpawnRule

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
    # S27: the world's populations as spawn rules. Omitted means one
    # population — S09's shape, holding every founding agent.
    populations: list[dict] | None = None
    # S33: the experiment-wide compute budget, shared by every agent.
    # Kinds omitted are unlimited; the constraint is opt-in.
    compute_budget: dict | None = None
    # S39: found the world from a named template instead of ad hoc
    # dimensions. When set, the template supplies width, height, agents
    # and the population rotation; the seed stays the caller's.
    template: str | None = None
    # S43: give the world life and climate. Off by default, so an
    # ordinary world is exactly what it was before the ecosystem existed.
    ecosystem: bool = False


class StartChallengeRequest(BaseModel):
    """S44: ask a world to do something measurable."""

    kind: str
    target: int | None = Field(default=None, ge=1)
    name: str | None = None


class SpawnRulePayload(BaseModel):
    """A population's spawn rule, as data (S27)."""

    name: str
    members: int = Field(default=1, ge=0, le=64)
    policies: list[str] = Field(default_factory=lambda: ["wander"])
    spawn_zone: list[int] | None = None
    max_members: int | None = Field(default=None, ge=0, le=256)
    top_up: bool = False
    stipend: dict[str, int] = Field(default_factory=dict)
    # S33: the compute this population's members may spend.
    tokens: float | None = Field(default=None, ge=0)
    model_calls: int | None = Field(default=None, ge=0)
    cpu_seconds: float | None = Field(default=None, ge=0)
    actions: int | None = Field(default=None, ge=0)


class BirthRequest(BaseModel):
    parent_id: int
    # S10: the four-part package the parent intends to pass on. When
    # omitted, the parent's pending intent (declared by its last
    # decision) is used.
    inheritance: dict | None = None


class ActionRequest(BaseModel):
    """An operator-injected action for one agent (S18).

    The seam a console/experiment uses to command an agent directly —
    the same validation path the agent's own decisions go through.
    """

    agent_id: int
    action: dict


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
        if payload.template:
            from app.experiments.multi_world import resolve_template

            template = resolve_template(payload.template)
            host = request.app.state.worlds.create(
                **template.world_kwargs(seed=payload.seed, tps=payload.tick_rate),
                autostart=payload.autostart,
                brains=payload.brains,
                ecosystem=payload.ecosystem,
            )
        else:
            host = request.app.state.worlds.create(
                seed=payload.seed,
                width=payload.width,
                height=payload.height,
                agents=payload.agents,
                tps=payload.tick_rate,
                autostart=payload.autostart,
                brains=payload.brains,
                populations=payload.populations,
                compute_budget=payload.compute_budget,
                ecosystem=payload.ecosystem,
            )
    except ValueError as exc:
        # Unknown brains, a bad spawn rule, an unknown template, or a
        # misconfigured model provider.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _state(host)


@router.get("/templates")
def list_templates() -> dict:
    """S39: the world recipes a laboratory can stamp out."""
    from app.experiments.multi_world import TEMPLATES

    return {"templates": [template.to_dict() for template in TEMPLATES.values()]}


@router.get("/genetics")
def genetics_library() -> dict:
    """S41: the gene shelf — every agent's bounded genome, described."""
    from app.simulation.genetics import mutation_catalog

    return mutation_catalog()


@router.get("/ecosystem")
def ecosystem_library() -> dict:
    """S43: the ecosystem shelf — species, weather, seasons, caps."""
    from app.simulation.ecosystem import ecosystem_catalog

    return ecosystem_catalog()


@router.get("/challenges")
def challenge_library() -> dict:
    """S44: the challenge shelf — metrics, completion rules, requirements."""
    from app.simulation.challenges import challenge_catalog

    return challenge_catalog()


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


# ----------------------------------------------------------------------
# Persistence (S38)
# ----------------------------------------------------------------------


@router.post("/worlds/{world_id}/snapshots", status_code=201)
def save_world_snapshot(world_id: int, request: Request, kind: str = "manual") -> dict:
    """Save the world now — the grid and everything it has become."""
    host = _host(request, world_id)
    if kind not in ("manual", "archive"):
        raise HTTPException(status_code=400, detail=f"unknown snapshot kind {kind!r}")
    snapshot_id = host.save(kind)
    return {"world_id": world_id, "snapshot_id": snapshot_id, "kind": kind}


@router.get("/worlds/{world_id}/snapshots")
def list_world_snapshots(world_id: int, request: Request, limit: int = 50) -> dict:
    from app.persistence.repositories import SnapshotRepository

    _host(request, world_id)
    rows = SnapshotRepository(
        request.app.state.worlds.session_factory
    ).list(world_id, limit=max(1, min(limit, 500)))
    return {
        "world_id": world_id,
        "snapshots": [
            {
                "id": row.id,
                "tick": row.tick,
                "kind": row.kind,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.post("/worlds/{world_id}/restore", status_code=201)
async def restore_world(
    world_id: int, request: Request, snapshot_id: int | None = None
) -> dict:
    """Bring a stopped world back — from its newest snapshot, or a
    chosen one. The world resumes exactly as it stood."""
    try:
        host = await request.app.state.worlds.resume(
            world_id, snapshot_id, autostart=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _state(host)


@router.get("/worlds/{world_id}/snapshots/{snapshot_id}")
def get_world_snapshot(world_id: int, snapshot_id: int, request: Request) -> dict:
    from app.persistence.repositories import SnapshotRepository

    _host(request, world_id)
    row = SnapshotRepository(request.app.state.worlds.session_factory).get(snapshot_id)
    if row is None or row.world_id != world_id:
        raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not in world {world_id}")
    return {"world_id": world_id, "snapshot": {"id": row.id, "tick": row.tick, "kind": row.kind}}


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
            # S33: what this agent may still spend, by kind.
            "budget": host.engine.world.budget_view(agent.agent_id),
        },
        "resources": host.engine.world.resources(agent.agent_id),
        # S29: what this agent knows how to make, and what it carries.
        "technology": {
            "recipes": host.engine.world.known_recipes(agent.agent_id),
            "patterns": host.engine.world.known_patterns(agent.agent_id),
            "carried": host.engine.world.carried_objects(agent.agent_id),
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
        # S41: this agent's bounded genome.
        "genome": agent.genome.to_dict(),
        # S30: the community this agent belongs to (or None).
        "settlement": host.engine.world.settlement_view(agent.agent_id),
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

    # S41: the mutation recorded at each birth, keyed by child id.
    mutations_by_child: dict[int, list] = {}
    for event in host.engine.world.events:
        if event.type == EventTypes.GENES_INHERITED and event.target_id is not None:
            mutations_by_child[event.target_id] = list(
                event.payload.get("mutations") or []
            )

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
                "genome": member.genome.to_dict(),
                "mutations": mutations_by_child.get(member.agent_id, []),
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


@router.post("/worlds/{world_id}/actions")
def inject_action(world_id: int, payload: ActionRequest, request: Request) -> dict:
    """S18: run one action for one agent (operator injection).

    The action travels the same validated path as the agent's own
    decisions — the world still decides everything. The response is the
    ActionResult, so a caller sees exactly what the world made of it.
    """
    host = _host(request, world_id)
    if host.engine.world.entity_position(payload.agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"entity {payload.agent_id} not in world {world_id}",
        )
    result = host.engine.world.execute_action(payload.agent_id, payload.action)
    return {
        "ok": result.ok,
        "reason": result.reason,
        "action": result.action,
        "data": result.data,
        "event_id": result.event.id,
    }


@router.get("/worlds/{world_id}/language")
def get_language(world_id: int, request: Request) -> dict:
    """S42: every repertoire, the words shared, and how far it agrees.

    Agreement is mean pairwise Jaccard over concept→symbol pairs, so the
    number rises only when agents use the *same* symbol for a concept.
    """
    host = _host(request, world_id)
    return {"world_id": world_id, **host.engine.world.language_summary()}


@router.post("/worlds/{world_id}/language/speak")
def speak_language(
    world_id: int, payload: LanguageSpeakRequest, request: Request
) -> dict:
    """S42: speak in the agent's own language, inventing missing words."""
    host = _host(request, world_id)
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="empty_message")
    try:
        event = host.engine.world.speak(payload.speaker_id, payload.message.strip())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "event_id": event.id,
        "speaker_id": payload.speaker_id,
        "message": event.payload["message"],
        "text": event.payload["text"],
        "symbols": event.payload["symbols"],
    }


@router.post("/worlds/{world_id}/language/learn")
def learn_language(
    world_id: int, payload: LanguageLearnRequest, request: Request
) -> dict:
    """S42: adopt the words from a speaker's most recent utterance."""
    host = _host(request, world_id)
    try:
        changes = host.engine.world.learn(payload.listener_id, payload.speaker_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "listener_id": payload.listener_id,
        "speaker_id": payload.speaker_id,
        "learned": changes,
        "lexicon": host.engine.world.lexicon(payload.listener_id).entries,
    }


@router.get("/worlds/{world_id}/ecosystem")
def get_ecosystem(world_id: int, request: Request) -> dict:
    """S43: season, weather, plant biomass, herds, caps, and food chain."""
    host = _host(request, world_id)
    world = host.engine.world
    if world.ecosystem is None:
        return {"world_id": world_id, "enabled": False}
    return {"world_id": world_id, **world.ecosystem.summary(world)}


@router.get("/worlds/{world_id}/challenges")
def list_challenges(world_id: int, request: Request) -> dict:
    """S44: every challenge and its live metric."""
    host = _host(request, world_id)
    return {
        "world_id": world_id,
        "challenges": [
            challenge.to_dict(reveal=False)
            for challenge in host.engine.world.challenges
        ],
    }


@router.post("/worlds/{world_id}/challenges", status_code=201)
def start_challenge(
    world_id: int, payload: StartChallengeRequest, request: Request
) -> dict:
    """S44: begin a challenge; its metric is derived from world facts."""
    host = _host(request, world_id)
    try:
        challenge = host.engine.world.start_challenge(
            payload.kind,
            target=payload.target,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "world_id": world_id,
        "challenge": challenge.to_dict(reveal=False),
    }


@router.get("/worlds/{world_id}/challenges/{challenge_id}")
def get_challenge(world_id: int, challenge_id: int, request: Request) -> dict:
    """S44: one challenge's metric and verdict (discovery reveals on win)."""
    host = _host(request, world_id)
    challenge = host.engine.world.challenge(challenge_id)
    if challenge is None:
        raise HTTPException(
            status_code=404,
            detail=f"challenge {challenge_id} not in world {world_id}",
        )
    return {
        "world_id": world_id,
        "challenge": challenge.to_dict(reveal=False),
    }


class ParticipantMoveRequest(BaseModel):
    direction: str


class LanguageSpeakRequest(BaseModel):
    speaker_id: int
    message: str


class LanguageLearnRequest(BaseModel):
    listener_id: int
    speaker_id: int


class ChatRequest(BaseModel):
    agent_id: int
    message: str


class SocialLeg(BaseModel):
    object_id: int | None = None
    resource: str | None = None
    amount: int = 1


class SocialRequest(BaseModel):
    agent_id: int
    leg: SocialLeg


class TradeRequest(BaseModel):
    agent_id: int
    give: SocialLeg
    want: SocialLeg


class GroupRequest(BaseModel):
    radius: int = 6
    following: bool = True


@router.post("/worlds/{world_id}/give")
def participant_give(world_id: int, payload: SocialRequest, request: Request) -> dict:
    """S22: hand something you carry to an adjacent agent."""
    host = _host(request, world_id)
    leg = payload.leg.model_dump(exclude_none=True)
    return host.social_give(agent_id=payload.agent_id, leg=leg)


@router.post("/worlds/{world_id}/take")
def participant_take(world_id: int, payload: SocialRequest, request: Request) -> dict:
    """S22: take something an adjacent agent carries."""
    host = _host(request, world_id)
    leg = payload.leg.model_dump(exclude_none=True)
    return host.social_take(agent_id=payload.agent_id, leg=leg)


@router.post("/worlds/{world_id}/trade")
def participant_trade(world_id: int, payload: TradeRequest, request: Request) -> dict:
    """S22: swap with an adjacent agent, atomically."""
    host = _host(request, world_id)
    return host.social_trade(
        agent_id=payload.agent_id,
        give=payload.give.model_dump(exclude_none=True),
        want=payload.want.model_dump(exclude_none=True),
    )


@router.post("/worlds/{world_id}/group")
def participant_group(world_id: int, payload: GroupRequest, request: Request) -> dict:
    """S22: nearby agents start — or stop — following the participant."""
    host = _host(request, world_id)
    return host.social_group(radius=payload.radius, following=payload.following)


@router.get("/worlds/{world_id}/participant")
def get_participant(world_id: int, request: Request) -> dict:
    """S20: is the operator in this world, and where?"""
    host = _host(request, world_id)
    return {"world_id": world_id, "participant": host.participant}


@router.post("/worlds/{world_id}/participant/join")
def join_participant(world_id: int, request: Request) -> dict:
    """S20: enter the world as an entity. The simulation keeps running."""
    host = _host(request, world_id)
    result = host.participant_join()
    return {"world_id": world_id, **result}


@router.post("/worlds/{world_id}/participant/leave")
def leave_participant(world_id: int, request: Request) -> dict:
    """S20: leave the world."""
    host = _host(request, world_id)
    result = host.participant_leave()
    return {"world_id": world_id, **result}


@router.post("/worlds/{world_id}/chat")
async def chat_with_agent(world_id: int, payload: ChatRequest, request: Request) -> dict:
    """S21: say something to one agent and receive its answer.

    The participant must be in the world and within earshot of the
    target (local speech). The reply is the agent's own — a model mind
    answers from its observation, which now carries what was said.
    """
    host = _host(request, world_id)
    return await host.converse(agent_id=payload.agent_id, message=payload.message)


@router.get("/worlds/{world_id}/conversations")
def list_conversations(world_id: int, request: Request, limit: int = 100) -> dict:
    """S21: the conversation log — every utterance on this world's
    timeline, oldest first (SPEECH from anyone, agents' replies
    included)."""
    host = _host(request, world_id)
    limit = max(1, min(limit, 1000))
    utterances = [
        {
            "id": event.id,
            "tick": event.tick,
            "from": event.actor_id,
            "kind": "agent" if event.actor_id != PARTICIPANT_ENTITY_ID else "participant",
            "message": event.payload.get("message"),
        }
        for event in host.engine.world.events
        if event.type in (EventTypes.SPEECH, EventTypes.AGENT_MESSAGE)
    ]
    return {"world_id": world_id, "conversations": utterances[-limit:]}


@router.post("/worlds/{world_id}/participant/move")
def move_participant(world_id: int, payload: ParticipantMoveRequest, request: Request) -> dict:
    """S20: walk the avatar. The move travels the same validated path as
    an agent's — walls, water and occupants all still apply."""
    host = _host(request, world_id)
    if host.participant is None:
        raise HTTPException(status_code=409, detail="no participant in this world; join first")
    result = host.engine.world.execute_action(
        PARTICIPANT_ENTITY_ID, {"action": "move", "direction": payload.direction}
    )
    return {
        "world_id": world_id,
        "ok": result.ok,
        "reason": result.reason,
        "position": (
            host.engine.world.entity_position(PARTICIPANT_ENTITY_ID).to_dict()
            if host.participant
            else None
        ),
    }


@router.get("/worlds/{world_id}/structures")
def list_structures(world_id: int, request: Request) -> dict:
    """S18: the world's structures — buildings as collections of blocks."""
    host = _host(request, world_id)
    structures = []
    for structure in host.engine.world.structures():
        components = []
        for object_id in structure.components:
            obj = host.engine.world.get_object(object_id)
            if obj is None:  # pragma: no cover - structure and objects agree
                continue
            components.append(
                {
                    "object_id": obj.id,
                    "type": obj.type,
                    "position": obj.position.to_dict() if obj.position else None,
                    "placed_by": obj.properties.get("placed_by"),
                }
            )
        structures.append(
            {
                "id": structure.id,
                "owner": structure.owner,
                "purpose": structure.purpose,
                "component_count": len(structure.components),
                "components": components,
            }
        )
    return {"world_id": world_id, "structures": structures}


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


# ----------------------------------------------------------------------
# Populations (S27)
# ----------------------------------------------------------------------


def _populations(request: Request, world_id: int) -> PopulationManager:
    host = _host(request, world_id)
    manager = host.engine.populations
    if manager is None:  # pragma: no cover - every created world has one
        raise HTTPException(status_code=409, detail=f"world {world_id} has no populations")
    return manager


@router.get("/worlds/{world_id}/populations")
def list_populations(world_id: int, request: Request) -> dict:
    """Every population in the world, with statistics.

    The groups themselves — sizes, generations, resources, births,
    arrivals — straight from the manager, so two populations sharing
    one world are as visible as two agents sharing one cell.
    """
    return {"world_id": world_id, **_populations(request, world_id).world_statistics()}


@router.post("/worlds/{world_id}/populations", status_code=201)
def create_population(world_id: int, payload: SpawnRulePayload, request: Request) -> dict:
    """Found a new population in a live world, from its spawn rule.

    The world keeps running while the group takes shape: the rule gets
    a database row, the founding members appear through the engine's
    spawn path, and they are visible to the other populations at once.
    """
    _populations(request, world_id)
    rule = SpawnRule(
        name=payload.name,
        members=payload.members,
        policies=tuple(payload.policies),
        spawn_zone=tuple(payload.spawn_zone) if payload.spawn_zone else None,
        max_members=payload.max_members,
        top_up=payload.top_up,
        stipend=dict(payload.stipend),
        tokens=payload.tokens,
        model_calls=payload.model_calls,
        cpu_seconds=payload.cpu_seconds,
        actions=payload.actions,
    )
    try:
        statistics = request.app.state.worlds.add_population(world_id, rule)
    except ValueError as exc:  # a rule the world cannot honor (bad zone, ...)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"world_id": world_id, "population": statistics}


@router.get("/worlds/{world_id}/populations/{population_id}")
def get_population(world_id: int, population_id: int, request: Request) -> dict:
    manager = _populations(request, world_id)
    try:
        statistics = manager.statistics(population_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"world_id": world_id, "population": statistics}


@router.get("/worlds/{world_id}/agents/{agent_id}/relationships")
def get_relationships(world_id: int, agent_id: int, request: Request) -> dict:
    """How one agent stands to every other (S27).

    Kin from the lineage, following and teams from the world,
    population membership — the social map, derived rather than stored,
    so it can never disagree with the world it describes.
    """
    manager = _populations(request, world_id)
    try:
        relationships = manager.relationships(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"world_id": world_id, "agent_id": agent_id, "relationships": relationships}


@router.get("/worlds/{world_id}/technology")
def get_technology(world_id: int, request: Request) -> dict:
    """S29: the world's technology — every recipe and pattern it has
    ever known, and the inventions on its timeline.

    Culture's ledger: what has been discovered, what has been
    invented, and by whom.
    """
    host = _host(request, world_id)
    world = host.engine.world
    inventions = [
        {
            "tick": event.tick,
            "actor_id": event.actor_id,
            "kind": event.payload.get("kind"),
            **({k: v for k, v in event.payload.items() if k != "kind"}),
        }
        for event in world.events
        if event.type == EventTypes.INVENTION
    ]
    return {
        "world_id": world_id,
        "recipes": [recipe.to_dict() for recipe in world.recipes.values()],
        "patterns": [pattern.to_dict() for pattern in world.patterns.values()],
        "inventions": inventions,
    }


def _settlement_stats(world, settlement) -> dict:
    """One settlement's statistics for the API (S30)."""
    zones = []
    for object_id, resource in settlement.zones.items():
        obj = world.get_object(object_id)
        zones.append(
            {
                "object_id": object_id,
                "resource": resource,
                "position": obj.position.to_dict() if obj and obj.position else None,
            }
        )
    roads = [road for road in world.roads if road.settlement_id == settlement.id]
    return {
        **settlement.to_dict(),
        "homes": len(settlement.home_ids),
        "storage": len(settlement.storage_ids),
        "roads": len(roads),
        "road_cells": [cell.to_dict() for road in roads for cell in road.cells],
        "members_with_roles": [
            {"agent_id": agent_id, "role": settlement.role_of(agent_id)}
            for agent_id in sorted(settlement.members)
        ],
        "zones": zones,
        "contents": dict(settlement.storage),
        "age_ticks": world.tick - settlement.founded_tick,
    }


@router.get("/worlds/{world_id}/settlements")
def list_settlements(world_id: int, request: Request) -> dict:
    """S30: the world's settlements — the communities standing in it.

    Each carries its identity, members with roles, homes, storehouse,
    roads, held zones and shared contents.
    """
    host = _host(request, world_id)
    world = host.engine.world
    return {
        "world_id": world_id,
        "settlements": [_settlement_stats(world, s) for s in world.settlements],
    }


@router.get("/worlds/{world_id}/settlements/{settlement_id}")
def get_settlement(world_id: int, settlement_id: int, request: Request) -> dict:
    host = _host(request, world_id)
    world = host.engine.world
    settlement = world.settlement(settlement_id)
    if settlement is None:
        raise HTTPException(status_code=404, detail=f"settlement {settlement_id} not in world {world_id}")
    return {"world_id": world_id, "settlement": _settlement_stats(world, settlement)}


# ----------------------------------------------------------------------
# Games (S31)
# ----------------------------------------------------------------------


class GameJoinRequest(BaseModel):
    entity_id: int


class GameMoveRequest(BaseModel):
    move: str


def _session_view(world, session, entity_id: int | None = None) -> dict:
    """One table as a viewer sees it: rules, seats, state, score,
    history — plus your own turn and legal moves when seated."""
    view = session.to_dict()
    view["your_turn"] = entity_id is not None and entity_id == session.current_player
    view["legal_moves"] = session.legal_moves(entity_id) if entity_id else []
    return view


@router.get("/worlds/{world_id}/games")
def list_games(world_id: int, request: Request) -> dict:
    """S31: every game proposed in this world — the rules as data."""
    return {"world_id": world_id, "games": _host(request, world_id).engine.world.games}


@router.post("/worlds/{world_id}/games", status_code=201)
def propose_game(world_id: int, payload: dict, request: Request) -> dict:
    """Propose a game: its rules, validated and recorded.

    The body is the rules mapping (name, players, setup, moves, win).
    Unplayable rules are a 400 with their reasons — the engine only
    plays data it understands, so the refusal *is* the safety
    guarantee the sprint's verification asks for.
    """
    host = _host(request, world_id)
    try:
        game = host.engine.world.propose_game(None, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"world_id": world_id, "game": game}


@router.post("/worlds/{world_id}/games/{game_id}/sessions", status_code=201)
def open_game_session(world_id: int, game_id: int, request: Request) -> dict:
    """Open a table for a proposed game: seats may be taken from now."""
    host = _host(request, world_id)
    world = host.engine.world
    try:
        session = world.open_session(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"world_id": world_id, "session": _session_view(world, session)}


@router.get("/worlds/{world_id}/games/sessions")
def list_game_sessions(world_id: int, request: Request) -> dict:
    """S31: every table in this world — an open one may still take a seat."""
    return {
        "world_id": world_id,
        "sessions": [_session_view(_host(request, world_id).engine.world, s) for s in _host(request, world_id).engine.world.sessions],
    }


@router.get("/worlds/{world_id}/games/sessions/{session_id}")
def get_game_session(world_id: int, session_id: int, request: Request, as_entity: int | None = None) -> dict:
    """One table; ``as_entity`` (the participant's id) sees its turn."""
    world = _host(request, world_id).engine.world
    session = world.session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not in world {world_id}")
    return {"world_id": world_id, "session": _session_view(world, session, as_entity)}


@router.post("/worlds/{world_id}/games/sessions/{session_id}/join", status_code=201)
def join_game(world_id: int, session_id: int, payload: GameJoinRequest, request: Request) -> dict:
    """Take a seat — the participant, or any entity id in the world."""
    host = _host(request, world_id)
    world = host.engine.world
    try:
        session = world.join_session(session_id, payload.entity_id)
    except ValueError as exc:
        detail = str(exc)
        if "unknown session" in detail:
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"world_id": world_id, "session": _session_view(world, session, payload.entity_id)}


@router.post("/worlds/{world_id}/games/sessions/{session_id}/moves", status_code=201)
def play_game_move(world_id: int, session_id: int, payload: GameMoveRequest, request: Request) -> dict:
    """Play a move at a table. The interpreter decides; the timeline
    records the move and, if it ended there, the winner."""
    host = _host(request, world_id)
    world = host.engine.world
    session = world.session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not in world {world_id}")
    participant = host.participant
    entity_id = participant["entity_id"] if participant else None
    if entity_id is None or entity_id not in session.players:
        raise HTTPException(status_code=409, detail="the participant is not seated at this table")
    try:
        outcome = world.play_move(session_id, entity_id, payload.move)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"world_id": world_id, "session": _session_view(world, session, entity_id), "move": outcome}
