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
from app.simulation.population import PopulationManager, SpawnRule
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
        # S27: the lineage recorder for this world, kept here so a
        # population founded later (the registry's add_population) can
        # teach the recorder its members' global ids.
        self.agent_recorder: AgentRecorder | None = None
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

        S27: spawn rules fire first. A population that tops up backfills
        itself before the world advances, so a death (once deaths
        exist) and a top-up look the same to the rule.
        """
        if self.engine.populations is not None:
            self.engine.populations.enforce_spawn_rules()
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
        populations: list[dict] | None = None,
    ) -> WorldHost:
        if brains not in _BRAINS:
            raise ValueError(f"unknown brains {brains!r}; expected one of {_BRAINS}")
        if populations is not None and not isinstance(populations, list):
            raise ValueError("populations must be a list of spawn rules")

        with self._session_factory() as session:
            row = WorldModel(name=f"world-{seed}", seed=str(seed))
            session.add(row)
            session.commit()
            world_id = row.id

            # One population per rule (S27). S09's "one population per
            # world" is now the default case: a single rule named after
            # the world, holding every founding agent, whose minds rotate
            # exactly as they always have.
            rules: list[SpawnRule] = []
            if populations is None:
                rules.append(
                    SpawnRule(
                        name=f"population-{world_id}",
                        members=agents,
                        # A model world's founding members are model
                        # minds (S08); scripted worlds rotate the three
                        # scripted minds (S17).
                        policies=("model",)
                        if brains == BRAINS_MODEL
                        else ("wander", "forage", "gather"),
                    )
                )
            else:
                for spec in populations:
                    rules.append(spec if isinstance(spec, SpawnRule) else SpawnRule.from_dict(spec))
            population_rows: list[PopulationModel] = []
            for rule in rules:
                population_row = PopulationModel(
                    name=rule.name, world_id=world_id, population_rules=rule.to_dict()
                )
                session.add(population_row)
                population_rows.append(population_row)
            session.commit()
            population_ids = [p.id for p in population_rows]

        bus = EventBus()
        bus.subscribe(DatabaseEventRecorder(self._session_factory, world_id))
        world = World.generate(seed, width, height, event_bus=bus)

        provider: ModelProvider | None = None
        if brains == BRAINS_MODEL:
            # One provider instance shared by every model agent; each
            # agent gets its own ModelPolicy, since a policy holds the
            # agent's in-flight decision (S08).
            provider = provider_from_settings(settings)

        def agent_factory(name: str, index: int) -> Agent:
            """A population member's body, by policy name (S27)."""
            if name == "model":
                if provider is None:
                    raise ValueError("a model policy needs a model world (brains='model')")
                return Agent(agent_id=-1, policy=ModelPolicy(provider), observation_radius=2)
            if name == "wander":
                return Agent(agent_id=-1, policy=WanderPolicy(), observation_radius=2)
            if name == "forage":
                return Agent(agent_id=-1, policy=ForagerPolicy(), observation_radius=2)
            if name == "gather":
                # The resource-driven mind starts at its resource: a
                # blind local search on a sparse map finds nothing (S17).
                return Agent(agent_id=-1, policy=GathererPolicy("wood"), observation_radius=4)
            raise ValueError(f"unknown policy {name!r} for a spawned agent")

        gatherer_spot = _gatherer_spot(world)
        spot_taken = False

        def cell_hint(name: str, index: int) -> Position | None:
            nonlocal spot_taken
            if name == "gather" and gatherer_spot is not None and not spot_taken:
                spot_taken = True
                return gatherer_spot
            return None

        engine = Engine(world, population_id=population_ids[0] if population_ids else None)
        manager = PopulationManager(engine, agent_factory=agent_factory, cell_hint=cell_hint)
        engine.populations = manager
        for population_id, rule in zip(population_ids, rules):
            manager.register(population_id, rule)
            manager.spawn_founding(population_id)

        # Founding agents get their rows now; births are persisted by
        # the AgentRecorder subscriber off the world's event bus.
        local_to_global: dict[int, int] = {}
        with self._session_factory() as session:
            for agent in engine.agents:
                record = AgentModel(
                    world_id=world_id,
                    local_id=agent.agent_id,
                    population_id=agent.population_id,
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
            if population_ids:
                population_row = session.get(PopulationModel, population_ids[0])
                population_row.root_agent_id = (
                    local_to_global[min(local_to_global)] if local_to_global else None
                )
            session.commit()

        # Births only happen after the founding generation, so the
        # lineage recorder can subscribe last — it ignores every other
        # event type.
        recorder = AgentRecorder(
            self._session_factory,
            world_id,
            population_ids[0] if population_ids else None,
            local_to_global,
        )
        bus.subscribe(recorder)

        host = WorldHost(world_id, engine, tps=tps, brains=brains, provider=provider)
        host.agent_recorder = recorder
        self._hosts[world_id] = host
        if autostart:
            host.start()
        return host

    def add_population(self, world_id: int, rule: dict | SpawnRule) -> dict:
        """Found a new population in a live world (S27).

        The world keeps running: the rule gets a database row, its
        founding members appear under the engine's spawn path, and the
        lineage recorder learns their global ids so future births link
        up like everyone else's.
        """
        host = self._hosts.get(world_id)
        if host is None:
            raise ValueError(f"world {world_id} is not live")
        rule = rule if isinstance(rule, SpawnRule) else SpawnRule.from_dict(rule)
        manager = host.engine.populations
        if manager is None:  # pragma: no cover - every created world has one
            raise ValueError(f"world {world_id} has no population manager")

        with self._session_factory() as session:
            population_row = PopulationModel(
                name=rule.name, world_id=world_id, population_rules=rule.to_dict()
            )
            session.add(population_row)
            session.commit()
            population_id = population_row.id

        manager.register(population_id, rule)
        members = manager.spawn_founding(population_id)
        recorder = host.agent_recorder
        with self._session_factory() as session:
            for agent in members:
                record = AgentModel(
                    world_id=world_id,
                    local_id=agent.agent_id,
                    population_id=population_id,
                    generation=agent.generation,
                    birth_tick=host.engine.world.tick,
                    status="active",
                    location=agent.position.to_dict() if agent.position else None,
                    inherited_traits={},
                    inherited_knowledge=[],
                    cultural_artifacts=[],
                )
                session.add(record)
                session.flush()
                if recorder is not None:
                    recorder.remember(agent.agent_id, record.id)
            session.commit()
        return manager.statistics(population_id)

    def get(self, world_id: int) -> WorldHost | None:
        return self._hosts.get(world_id)

    def all(self) -> list[WorldHost]:
        return [self._hosts[i] for i in sorted(self._hosts)]

    def remove(self, world_id: int) -> bool:
        return self._hosts.pop(world_id, None) is not None

    async def stop_all(self) -> None:
        for host in self.all():
            await host.stop()
