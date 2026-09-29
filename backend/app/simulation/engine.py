"""The tick loop: the world advances, then its inhabitants act.

Determinism contract: agents act in ascending agent_id order every tick,
and policies are pure functions of the observation. Two engines built
from the same seed and the same script produce identical histories.

Every agent acts every tick for now — a cognition scheduler (deciding
*which* agents think each tick) arrives when model calls make thinking
expensive (S08+).
"""

from __future__ import annotations

from app.simulation.actions import ActionResult
from app.simulation.agent import Agent
from app.simulation.world import Position, World


class Engine:
    def __init__(self, world: World) -> None:
        self.world = world
        self._agents: dict[int, Agent] = {}

    def spawn_agent(self, agent: Agent, position: Position) -> None:
        agent.spawn(self.world, position)
        self._agents[agent.agent_id] = agent

    @property
    def agents(self) -> list[Agent]:
        """All agents, in ascending agent_id order."""
        return [self._agents[i] for i in sorted(self._agents)]

    def step(self) -> list[ActionResult]:
        """One tick: world advances, then every agent observes-decides-acts."""
        self.world.step()
        return [agent.act() for agent in self.agents]

    def run(self, ticks: int) -> list[list[ActionResult]]:
        return [self.step() for _ in range(ticks)]
