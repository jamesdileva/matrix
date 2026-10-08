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

from app.simulation.actions import ActionResult
from app.simulation.agent import Agent
from app.simulation.events import EventTypes
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

    @property
    def has_model_policies(self) -> bool:
        """True when any agent's policy thinks asynchronously (S08)."""
        return any(hasattr(agent.policy, "refresh") for agent in self.agents)

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
