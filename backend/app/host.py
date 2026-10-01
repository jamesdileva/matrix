"""Live-world hosting: an asyncio tick loop per world.

The engine stays pure and synchronous; the host is the outer layer that
makes a world *run* — advancing it on a timer so clients can watch, with
pause/resume/manual-step for control and deterministic max-ticks runs for
tests.
"""

from __future__ import annotations

import asyncio

from app.persistence.models import WorldModel
from app.persistence.repositories import DatabaseEventRecorder
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.policies import ForagerPolicy, WanderPolicy
from app.simulation.world import Position, World


class WorldHost:
    def __init__(self, world_id: int, engine: Engine, tps: float = 6.0) -> None:
        if tps <= 0:
            raise ValueError(f"tick rate must be positive, got {tps}")
        self.world_id = world_id
        self.engine = engine
        self.tps = tps
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
                self.engine.step()
            await asyncio.sleep(interval)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def step_once(self) -> int:
        """Advance exactly one tick, regardless of pause state."""
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
    with scripted inhabitants, the event recorder subscribing to the
    world's bus, and a host ticking it. API routes read hosts from here.
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
    ) -> WorldHost:
        with self._session_factory() as session:
            row = WorldModel(name=f"world-{seed}", seed=str(seed))
            session.add(row)
            session.commit()
            world_id = row.id

        bus = EventBus()
        bus.subscribe(DatabaseEventRecorder(self._session_factory, world_id))
        world = World.generate(seed, width, height, event_bus=bus)
        engine = Engine(world)

        policies = [WanderPolicy(), ForagerPolicy()]
        spawned = 0
        for y in range(1, world.height - 1):
            for x in range(1, world.width - 1):
                if spawned >= agents:
                    break
                pos = Position(x, y)
                if world.is_floor(pos) and world.object_at(pos) is None:
                    engine.spawn_agent(
                        Agent(agent_id=spawned + 1, policy=policies[spawned % len(policies)]),
                        pos,
                    )
                    spawned += 1

        host = WorldHost(world_id, engine, tps=tps)
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
