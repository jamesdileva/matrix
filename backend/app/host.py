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

from app.config.settings import settings
from app.models.config import provider_from_settings
from app.models.provider import ModelProvider
from app.persistence.models import WorldModel
from app.persistence.repositories import DatabaseEventRecorder
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import ForagerPolicy, WanderPolicy
from app.simulation.world import Position, World

BRAINS_SCRIPTED = "scripted"
BRAINS_MODEL = "model"
_BRAINS = (BRAINS_SCRIPTED, BRAINS_MODEL)


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

        bus = EventBus()
        bus.subscribe(DatabaseEventRecorder(self._session_factory, world_id))
        world = World.generate(seed, width, height, event_bus=bus)
        engine = Engine(world)

        provider: ModelProvider | None = None
        if brains == BRAINS_MODEL:
            # One provider instance shared by every model agent; each
            # agent gets its own ModelPolicy, since a policy holds the
            # agent's in-flight decision (S08).
            provider = provider_from_settings(settings)
        policies = [WanderPolicy(), ForagerPolicy()]
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
                    engine.spawn_agent(
                        Agent(agent_id=spawned + 1, policy=policy),
                        pos,
                    )
                    spawned += 1

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
