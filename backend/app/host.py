"""Live-world hosting: an asyncio tick loop per world.

The engine stays pure and synchronous; the host is the outer layer that
makes a world *run* — advancing it on a timer so clients can watch, with
pause/resume/manual-step for control and deterministic max-ticks runs for
tests.

Worlds are scripted by default. `brains="model"` (S08) is an explicit
opt-in: the registry then builds model agents from the configured
provider, and the host advances them through `Engine.step_async`, which
awaits the provider between the world advancing and each agent acting.
A settings-configured provider alone never starts a model world — that
decision belongs to whoever creates the world.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from app.config.settings import settings
from app.models.config import provider_from_settings
from app.models.provider import ModelProvider
from app.persistence.models import AgentModel, PopulationModel, WorldModel
from app.persistence.repositories import AgentRecorder, DatabaseEventRecorder
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import ForagerPolicy, GathererPolicy, WanderPolicy
from app.simulation.world import SPEECH_RADIUS, Position, World

BRAINS_SCRIPTED = "scripted"
BRAINS_MODEL = "model"
_BRAINS = (BRAINS_SCRIPTED, BRAINS_MODEL)

# The participant's entity id, well above engine agent ids (S20). The
# participant is an entity like any other — it moves through the same
# validated dispatcher and appears in agents' observations.
PARTICIPANT_ENTITY_ID = 1001


def _gatherer_spot(world):
    """A floor cell next to a tree — where the wood gatherer starts (S17)."""
    for obj in world.objects:
        if obj.type != "tree" or obj.position is None:
            continue
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = Position(obj.position.x + dx, obj.position.y + dy)
            if world.is_floor(cell) and world.object_at(cell) is None:
                return cell
    return None


class WorldHost:
    def __init__(
        self,
        world_id: int,
        engine: Engine,
        tps: float = 6.0,
        *,
        brains: str = BRAINS_SCRIPTED,
        provider: ModelProvider | None = None,
    ) -> None:
        if tps <= 0:
            raise ValueError(f"tick rate must be positive, got {tps}")
        self.world_id = world_id
        self.engine = engine
        self.tps = tps
        self.brains = brains
        self.provider = provider
        self.paused = False
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, max_ticks: int | None = None) -> asyncio.Task:
        """Start ticking. `max_ticks` bounds the run (used by tests)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(max_ticks))
        return self._task

    async def _loop(self, max_ticks: int | None) -> None:
        interval = 1.0 / self.tps
        iterations = 0
        # The bound counts loop iterations, not completed ticks, so a
        # paused host still terminates a bounded run.
        while max_ticks is None or iterations < max_ticks:
            iterations += 1
            if not self.paused:
                await self.advance_once()
            await asyncio.sleep(interval)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def advance_once(self) -> list:
        """Advance one tick, model-aware: awaits providers when present.

        Works for both world kinds — scripted engines take the pure
        synchronous path inside.
        """
        if self.engine.has_model_policies:
            return await self.engine.step_async()
        return self.engine.step()

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    # ------------------------------------------------------------------
    # The participant (S20)
    # ------------------------------------------------------------------

    @property
    def participant(self) -> dict | None:
        """The world's participant, or None."""
        position = self.engine.world.entity_position(PARTICIPANT_ENTITY_ID)
        if position is None:
            return None
        return {"entity_id": PARTICIPANT_ENTITY_ID, "position": position.to_dict()}

    def participant_join(self) -> dict:
        """Enter the world as an entity on the first free floor cell.

        Idempotent: joining while present returns the current
        participant. The simulation keeps ticking throughout.
        """
        existing = self.participant
        if existing is not None:
            return {**existing, "joined": False}

        for y in range(1, self.engine.world.height - 1):
            for x in range(1, self.engine.world.width - 1):
                position = Position(x, y)
                if (
                    self.engine.world.is_floor(position)
                    and self.engine.world.object_at(position) is None
                    and self.engine.world.entity_at(position) is None
                ):
                    self.engine.world.add_entity(PARTICIPANT_ENTITY_ID, position)
                    return {
                        "entity_id": PARTICIPANT_ENTITY_ID,
                        "position": position.to_dict(),
                        "joined": True,
                    }
        raise HTTPException(status_code=409, detail="no free cell for a participant")

    def participant_leave(self) -> dict:
        """Leave the world; the entity (and its events) go with it."""
        if self.participant is None:
            return {"entity_id": PARTICIPANT_ENTITY_ID, "left": False}
        self.engine.world.remove_entity(PARTICIPANT_ENTITY_ID)
        return {"entity_id": PARTICIPANT_ENTITY_ID, "left": True}

    # ------------------------------------------------------------------
    # Conversation (S21)
    # ------------------------------------------------------------------

    async def converse(self, *, agent_id: int, message: str) -> dict:
        """Say something to one agent and get its answer.

        The participant speaks through the same validated `say` action
        as anyone else, the target must be within earshot (local
        speech), and the agent answers on the spot — its next decision
        sees the message, so a model mind replies in kind. A scripted
        agent has nothing to say; the speech is still recorded and the
        reply is simply absent.
        """
        participant = self.participant
        if participant is None:
            raise HTTPException(status_code=409, detail="no participant in this world; join first")
        target = next(
            (a for a in self.engine.agents if a.agent_id == agent_id), None
        )
        if target is None:
            raise HTTPException(status_code=404, detail=f"agent {agent_id} not in world")

        said = self.engine.world.execute_action(
            PARTICIPANT_ENTITY_ID, {"action": "say", "message": message}
        )
        if not said.ok:
            raise HTTPException(status_code=400, detail=f"could not speak: {said.reason}")

        listener = self.engine.world.entity_position(agent_id)
        speaker = self.engine.world.entity_position(PARTICIPANT_ENTITY_ID)
        if listener is None:  # pragma: no cover - target existence just checked
            raise HTTPException(status_code=409, detail="the agent left the world")
        distance = abs(listener.x - speaker.x) + abs(listener.y - speaker.y)
        if distance > SPEECH_RADIUS:
            raise HTTPException(
                status_code=400,
                detail=f"agent {agent_id} is out of earshot ({distance} cells away, "
                f"radius {SPEECH_RADIUS})",
            )

        reply = await self._agent_reply(target)
        return {
            "agent_id": agent_id,
            "heard": True,
            "speech_event_id": said.event.id,
            "reply": reply.get("message") if reply else None,
            "reply_event_id": reply.get("event_id") if reply else None,
            "distance": distance,
        }

    async def _agent_reply(self, agent) -> dict | None:
        """Let one agent decide now; return its utterance if it made one."""
        refresh = getattr(agent.policy, "refresh", None)
        decision = None
        if refresh is not None:
            decision = await refresh(agent.observe())
        else:
            decision = agent.policy.decide(agent.observe())
        if not isinstance(decision, dict):
            return None
        message = decision.get("message")
        if not isinstance(message, str) or not message.strip():
            return None
        # The utterance rides the timeline like any other speech.
        event = self.engine.world.say(agent.agent_id, message.strip())
        return {"message": message.strip(), "event_id": event.id}

    # ------------------------------------------------------------------
    # Social interaction, participant-facing (S22)
    # ------------------------------------------------------------------

    def _participant_social(self, action: dict):
        """Run one social action as the participant; returns the result."""
        if self.participant is None:
            raise HTTPException(status_code=409, detail="no participant in this world; join first")
        result = self.engine.world.execute_action(PARTICIPANT_ENTITY_ID, action)
        if not result.ok:
            raise HTTPException(status_code=400, detail=result.reason or "rejected")
        return result

    def social_give(self, *, agent_id: int, leg: dict) -> dict:
        result = self._participant_social({"action": "give", "target": agent_id, **leg})
        return {"world_id": self.world_id, "ok": True, "data": result.data}

    def social_take(self, *, agent_id: int, leg: dict) -> dict:
        result = self._participant_social({"action": "take", "target": agent_id, **leg})
        return {"world_id": self.world_id, "ok": True, "data": result.data}

    def social_trade(self, *, agent_id: int, give: dict, want: dict) -> dict:
        result = self._participant_social(
            {"action": "trade", "target": agent_id, "give": give, "want": want}
        )
        return {"world_id": self.world_id, "ok": True, "data": result.data}

    def social_group(self, *, radius: int, following: bool) -> dict:
        """Sweep nearby agents into (or out of) following the participant.

        The operator's sweep, distinct from the `follow` action: agents
        need not start adjacent — the engine walks them over. Unfollowing
        an agent that is not following is simply not counted.
        """
        if self.participant is None:
            raise HTTPException(status_code=409, detail="no participant in this world; join first")
        here = self.engine.world.entity_position(PARTICIPANT_ENTITY_ID)
        changed = []
        for agent in self.engine.agents:
            position = agent.position
            if position is None:
                continue
            if abs(position.x - here.x) + abs(position.y - here.y) > radius:
                continue
            if following:
                self.engine.world.set_follow(agent.agent_id, PARTICIPANT_ENTITY_ID)
                self.engine.world._add_event(
                    EventTypes.FOLLOW,
                    actor_id=agent.agent_id,
                    target_id=PARTICIPANT_ENTITY_ID,
                    payload={"kind": "started", "via": "group"},
                )
                changed.append(agent.agent_id)
            elif self.engine.world.clear_follow(agent.agent_id):
                self.engine.world._add_event(
                    EventTypes.FOLLOW,
                    actor_id=agent.agent_id,
                    payload={"kind": "stopped", "via": "group"},
                )
                changed.append(agent.agent_id)
        return {
            "world_id": self.world_id,
            "following": following,
            "agents": changed,
        }


class WorldRegistry:
    """All live worlds in this process, bound to their database rows.

    Creation wires the full chain: a `WorldModel` row, a generated world
    with inhabitants, the event recorder subscribing to the world's bus,
    and a host ticking it. API routes read hosts from here.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._hosts: dict[int, WorldHost] = {}

    def create(
        self,
        *,
        seed: str = "void",
        width: int = 32,
        height: int = 32,
        agents: int = 3,
        tps: float = 6.0,
        autostart: bool = True,
        brains: str = BRAINS_SCRIPTED,
    ) -> WorldHost:
        if brains not in _BRAINS:
            raise ValueError(f"unknown brains {brains!r}; expected one of {_BRAINS}")

        with self._session_factory() as session:
            row = WorldModel(name=f"world-{seed}", seed=str(seed))
            session.add(row)
            session.commit()
            world_id = row.id

            # S09: one population per world. The engine's population id
            # IS the database row's id, so engine and DB agree on
            # membership without a translation layer.
            population = PopulationModel(name=f"population-{world_id}", world_id=world_id)
            session.add(population)
            session.commit()
            population_id = population.id

        bus = EventBus()
        bus.subscribe(DatabaseEventRecorder(self._session_factory, world_id))
        world = World.generate(seed, width, height, event_bus=bus)
        engine = Engine(world, population_id=population_id)

        provider: ModelProvider | None = None
        if brains == BRAINS_MODEL:
            # One provider instance shared by every model agent; each
            # agent gets its own ModelPolicy, since a policy holds the
            # agent's in-flight decision (S08).
            provider = provider_from_settings(settings)
        # Scripted minds rotate: a wanderer, a forager, a gatherer
        # (S17 — the resource-driven one makes scarcity visible).
        policies = [WanderPolicy(), ForagerPolicy(), GathererPolicy("wood")]
        gatherer_spot = _gatherer_spot(world)
        spawned = 0
        for y in range(1, world.height - 1):
            for x in range(1, world.width - 1):
                if spawned >= agents:
                    break
                pos = Position(x, y)
                if world.is_floor(pos) and world.object_at(pos) is None:
                    if provider is not None:
                        policy = ModelPolicy(provider)
                    else:
                        policy = policies[spawned % len(policies)]
                    radius = 4 if isinstance(policy, GathererPolicy) else 2
                    if isinstance(policy, GathererPolicy) and gatherer_spot is not None:
                        # The resource-driven mind starts at its resource:
                        # a blind local search on a sparse map finds
                        # nothing (S17).
                        pos = gatherer_spot
                        gatherer_spot = None
                    engine.spawn_agent(
                        Agent(agent_id=spawned + 1, policy=policy, observation_radius=radius),
                        pos,
                    )
                    spawned += 1

        # Founding agents get their rows now; births are persisted by
        # the AgentRecorder subscriber off the world's event bus.
        local_to_global: dict[int, int] = {}
        with self._session_factory() as session:
            for agent in engine.agents:
                record = AgentModel(
                    world_id=world_id,
                    local_id=agent.agent_id,
                    population_id=population_id,
                    generation=agent.generation,
                    birth_tick=0,
                    status="active",
                    location=agent.position.to_dict() if agent.position else None,
                    inherited_traits={},
                    inherited_knowledge=[],
                    cultural_artifacts=[],
                )
                session.add(record)
                session.flush()
                local_to_global[agent.agent_id] = record.id
            population_row = session.get(PopulationModel, population_id)
            population_row.root_agent_id = (
                local_to_global[min(local_to_global)] if local_to_global else None
            )
            session.commit()

        # Births only happen after the founding generation, so the
        # lineage recorder can subscribe last — it ignores every other
        # event type.
        bus.subscribe(AgentRecorder(self._session_factory, world_id, population_id, local_to_global))

        host = WorldHost(world_id, engine, tps=tps, brains=brains, provider=provider)
        self._hosts[world_id] = host
        if autostart:
            host.start()
        return host

    def get(self, world_id: int) -> WorldHost | None:
        return self._hosts.get(world_id)

    def all(self) -> list[WorldHost]:
        return [self._hosts[i] for i in sorted(self._hosts)]

    def remove(self, world_id: int) -> bool:
        return self._hosts.pop(world_id, None) is not None

    async def stop_all(self) -> None:
        for host in self.all():
            await host.stop()
