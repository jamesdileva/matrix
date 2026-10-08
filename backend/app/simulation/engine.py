"""The tick loop: the world advances, then its inhabitants act.

Determinism contract: agents act in ascending agent_id order every tick,
and policies are pure functions of the observation. Two engines built
from the same seed and the same script produce identical histories.

Every agent acts every tick for now — a cognition scheduler (deciding
*which* agents think each tick) arrives when model calls make thinking
expensive (S08+).

Model minds (S08) think asynchronously: their policy exposes a
``refresh`` coroutine that the loop awaits *between* the world advancing
and the agent acting. ``step_async`` is that loop; ``step`` remains the
pure-synchronous path for scripted worlds and is byte-for-byte what it
was before.
"""

from __future__ import annotations

import copy

from app.simulation.actions import ActionResult
from app.simulation.agent import Agent
from app.simulation.errors import BirthError
from app.simulation.events import EventTypes
from app.simulation.inheritance import InheritancePackage
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, World


class Engine:
    def __init__(self, world: World, population_id: int | None = None) -> None:
        self.world = world
        self.population_id = population_id
        self._agents: dict[int, Agent] = {}

    def spawn_agent(self, agent: Agent, position: Position) -> None:
        agent.spawn(self.world, position)
        if agent.population_id is None:
            agent.population_id = self.population_id
        self._agents[agent.agent_id] = agent

    @property
    def agents(self) -> list[Agent]:
        """All agents, in ascending agent_id order."""
        return [self._agents[i] for i in sorted(self._agents)]

    @property
    def has_model_policies(self) -> bool:
        """True when any agent's policy thinks asynchronously (S08)."""
        return any(hasattr(agent.policy, "refresh") for agent in self.agents)

    def population(self, population_id: int | None = None) -> list[Agent]:
        """Members of a population (this engine's, by default)."""
        wanted = self.population_id if population_id is None else population_id
        return [a for a in self.agents if a.population_id == wanted]

    def _next_agent_id(self) -> int:
        return max(self._agents, default=0) + 1

    def create_child(
        self,
        parent_id: int,
        *,
        policy=None,
        position: Position | None = None,
        inheritance: "dict | InheritancePackage | None" = None,
    ) -> Agent:
        """Reproduce: one parent, one child, one linked lineage (S09).

        **Inheritance (S10).** The child receives the parent's
        *intended* package — the ``inheritance`` argument, or the
        parent's pending intent declared by its last decision. Four
        parts travel (roadmap): traits, knowledge, message, cultural
        artifacts. A parent's own state that the package does not carry
        never reaches the child: uninherited memory does not
        magically appear. Everything is deep-copied, so parent and
        child are independent from the moment of birth, and the
        package recorded on the AGENT_BORN event never aliases later
        mutation of either.

        Placement is deterministic: the first free floor cell adjacent
        to the parent in N → E → S → W order, or an explicit position.
        No room raises `BirthError`; nothing is half-applied.
        """
        parent = self._agents.get(parent_id)
        if parent is None:
            raise ValueError(f"unknown parent agent {parent_id!r}")
        if parent.status != "alive":
            raise BirthError(f"parent {parent_id} is not alive")

        child_position = position if position is not None else self._free_adjacent(parent)
        if child_position is None:
            raise BirthError(f"no free cell adjacent to agent {parent_id}")

        package = InheritancePackage.from_dict(
            inheritance if inheritance is not None else parent.pending_inheritance
        )

        child = Agent(
            agent_id=self._next_agent_id(),
            policy=policy if policy is not None else WanderPolicy(),
            parent_id=parent.agent_id,
            generation=parent.generation + 1,
            population_id=parent.population_id,
        )
        # The package lands on the child as state — deep-copied, so
        # neither the parent's intent nor this event's payload can
        # alias the child's future edits.
        child.traits = copy.deepcopy(package.traits)
        child.knowledge = list(package.knowledge)
        child.cultural_artifacts = list(package.cultural_artifacts)
        child.inheritance_received = package.as_dict()
        # The parent's goal starts the child's, and the parent's
        # message is the child's first recollection (guide §10).
        child.goal = parent.goal
        child.memory.remember_action(
            tick=self.world.tick,
            action={"kind": "inheritance", "from": parent.agent_id},
            ok=True,
            reason=package.message,
            goal=child.goal,
        )
        self.spawn_agent(child, child_position)

        self.world._add_event(
            EventTypes.AGENT_BORN,
            actor_id=parent.agent_id,
            target_id=child.agent_id,
            payload={
                "parent_id": parent.agent_id,
                "child_id": child.agent_id,
                "generation": child.generation,
                "population_id": child.population_id,
                "position": child_position.to_dict(),
                "goal": child.goal,
                "inheritance": package.as_dict(),
            },
        )
        return child

    def ancestors(self, agent_id: int) -> list[Agent]:
        """The lineage from the root down to `agent_id` (inclusive)."""
        chain: list[Agent] = []
        current = self._agents.get(agent_id)
        while current is not None:
            chain.append(current)
            current = self._agents.get(current.parent_id) if current.parent_id else None
        return list(reversed(chain))

    def _free_adjacent(self, parent: Agent) -> Position | None:
        position = parent.position
        if position is None:  # pragma: no cover - status and registry agree
            return None
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):  # N, E, S, W
            candidate = Position(position.x + dx, position.y + dy)
            if (
                self.world.is_floor(candidate)
                and self.world.object_at(candidate) is None
                and self.world.entity_at(candidate) is None
            ):
                return candidate
        return None

    def step(self) -> list[ActionResult]:
        """One tick: world advances, then every agent observes-decides-acts."""
        self.world.step()
        return [agent.act() for agent in self.agents]

    async def step_async(self) -> list[ActionResult]:
        """One tick for minds that think asynchronously (S08).

        The world advances first, then each agent (ascending id,
        deterministic order) refreshes its model policy — awaiting the
        provider — before acting. Scripted policies have no ``refresh``
        and behave exactly as under ``step``.

        The decision, its outcome, any utterance, and any provider
        failure are recorded on the world timeline right after each
        agent acts (guide §7: store action, rationale, observation,
        outcome — the outcome of a *recorded* decision, never a re-call
        to the model).
        """
        self.world.step()
        results = []
        for agent in self.agents:
            refresh = getattr(agent.policy, "refresh", None)
            decision = observation = None
            if refresh is not None:
                observation = agent.observe()
                decision = await refresh(observation)
            result = agent.act()
            if refresh is not None:
                self._record_mind(agent, decision, observation, result)
            results.append(result)
        return results

    def _record_mind(
        self,
        agent: Agent,
        decision: dict | None,
        observation: dict | None,
        result: ActionResult,
    ) -> None:
        """Timeline events for one model agent's tick (S08)."""
        policy = agent.policy
        if decision is None:
            # The brain said nothing usable this tick. The agent already
            # acted via its safe fallback (a normal ACTION event); what
            # gets recorded here is *why* the brain was silent.
            self.world._add_event(
                EventTypes.MODEL_ERROR,
                actor_id=agent.agent_id,
                payload={
                    "reason": getattr(policy, "last_error", None) or "unknown",
                    "fallback_action": result.action,
                },
            )
            return

        message = decision.get("message")
        if isinstance(message, str) and message.strip():
            self.world._add_event(
                EventTypes.AGENT_MESSAGE,
                actor_id=agent.agent_id,
                payload={"message": message},
            )

        response = getattr(policy, "last_response", None)
        self.world._add_event(
            EventTypes.MODEL_DECISION,
            actor_id=agent.agent_id,
            payload={
                "provider": getattr(response, "provider", None),
                "model": getattr(response, "model", None),
                "decision": decision,
                "observation": observation,
                "outcome": {"ok": result.ok, "reason": result.reason},
            },
        )

    def run(self, ticks: int) -> list[list[ActionResult]]:
        return [self.step() for _ in range(ticks)]
