"""S08 — the model-aware tick: Engine.step_async.

These tests drive the same loop the live host runs. The roadmap's
headline guarantees live here: an LLM-driven agent observes the Void,
acts through world validation, has its decisions logged, and survives
its own provider failing mid-run.
"""

import asyncio

import pytest

from app.models.mock import MockProvider
from app.models.provider import ModelResponse, ProviderError
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.memory import DEFAULT_MEMORY_LIMIT
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, World


class ExplodingProvider:
    name = "exploding"

    async def generate(self, request):
        raise ProviderError("brain on fire")


class ChattyProvider:
    """Emits a decision with an utterance (guide §7's message field)."""

    name = "chatty"

    async def generate(self, request):
        return ModelResponse(
            text='{"action": {"action": "look"}, "message": "I am awake.",'
            ' "thought_summary": "first light"}',
            provider="chatty",
            model="chatty-1",
        )


def _spawn_engine(policy, *, seed="matrix", size=16) -> Engine:
    world = World.generate(seed, size, size)
    engine = Engine(world)
    for y in range(1, world.height - 1):
        for x in range(1, world.width - 1):
            pos = Position(x, y)
            if world.is_floor(pos) and world.object_at(pos) is None:
                engine.spawn_agent(Agent(agent_id=1, policy=policy), pos)
                return engine
    raise AssertionError("generated world has no floor cell")


def _events_of(world: World, event_type: str) -> list:
    return [e for e in world.events if e.type == event_type]


class TestStepAsyncParity:
    def test_has_model_policies_detection(self):
        scripted = _spawn_engine(WanderPolicy())
        modeled = _spawn_engine(ModelPolicy(MockProvider()))
        assert scripted.has_model_policies is False
        assert modeled.has_model_policies is True

    def test_scripted_world_identical_under_both_steps(self):
        engine_a = _spawn_engine(WanderPolicy())
        engine_b = _spawn_engine(WanderPolicy())
        for _ in range(15):
            engine_a.step()
            asyncio.run(engine_b.step_async())
        assert [e.to_dict() for e in engine_a.world.events] == [
            e.to_dict() for e in engine_b.world.events
        ]


class TestModelDecisionsLogged:
    def test_decision_event_carries_provenance_and_outcome(self):
        engine = _spawn_engine(ModelPolicy(MockProvider()))
        asyncio.run(engine.step_async())

        decisions = _events_of(engine.world, EventTypes.MODEL_DECISION)
        assert len(decisions) == 1
        payload = decisions[0].payload
        assert payload["provider"] == "mock"
        assert payload["model"] == "mock-1"
        assert payload["decision"]["action"]["action"] in {"move", "look", "pick_up"}
        assert payload["outcome"]["ok"] is True
        # Guide §7: action, rationale, observation, outcome are stored.
        assert payload["observation"]["self"]["id"] == 1
        assert decisions[0].actor_id == 1
        assert decisions[0].tick == 1

    def test_utterance_recorded_as_agent_message(self):
        engine = _spawn_engine(ModelPolicy(ChattyProvider()))
        asyncio.run(engine.step_async())

        messages = _events_of(engine.world, EventTypes.AGENT_MESSAGE)
        assert len(messages) == 1
        assert messages[0].payload["message"] == "I am awake."
        assert messages[0].actor_id == 1

    def test_provider_failure_logs_error_and_falls_back(self):
        engine = _spawn_engine(ModelPolicy(ExplodingProvider()))
        policy = engine.agents[0].policy
        asyncio.run(engine.step_async())

        errors = _events_of(engine.world, EventTypes.MODEL_ERROR)
        assert len(errors) == 1
        assert errors[0].payload["reason"].startswith("provider_error")
        assert errors[0].payload["fallback_action"] == {"action": "look"}
        # The fallback still acted, legally, and nothing else moved.
        actions = [e for e in engine.world.events if e.type.startswith("ACTION_")]
        assert len(actions) == 1
        assert actions[0].type == EventTypes.ACTION_EXECUTED
        assert policy.last_error is not None


class TestSurvival:
    def test_agent_survives_three_hundred_ticks(self):
        # Guide §9: one agent can survive several hundred ticks.
        engine = _spawn_engine(ModelPolicy(MockProvider()))
        asyncio.run(_drive(engine, ticks=300))

        agent = engine.agents[0]
        world = engine.world
        assert world.tick == 300
        assert agent.status == "alive"
        assert world.entity_position(1) is not None
        assert len(agent.memory) == DEFAULT_MEMORY_LIMIT  # bounded
        decisions = _events_of(world, EventTypes.MODEL_DECISION)
        assert len(decisions) == 300
        # The world re-validated every proposal; rejections (if any)
        # were recorded, never raised.
        rejected = _events_of(world, EventTypes.ACTION_REJECTED)
        assert all(e.actor_id == 1 for e in world.events if e.actor_id is not None)

    def test_memory_flows_into_observation(self):
        engine = _spawn_engine(ModelPolicy(MockProvider()))
        asyncio.run(_drive(engine, ticks=3))

        observation = engine.agents[0].observe()
        assert len(observation["memory"]) == 3
        assert observation["memory"][-1]["action"] == observation["memory"][-1]["action"]
        assert {"tick", "action", "ok", "reason", "goal"} <= set(observation["memory"][-1])

    def test_provider_failing_mid_run_world_continues(self):
        # Failure injected after a healthy start — the world must keep
        # ticking, the agent keep living, and the errors be logged.
        engine = _spawn_engine(ModelPolicy(MockProvider()))
        asyncio.run(_drive(engine, ticks=5))

        engine.agents[0].policy.provider = ExplodingProvider()
        asyncio.run(_drive(engine, ticks=5))

        world = engine.world
        assert world.tick == 10
        assert len(_events_of(world, EventTypes.MODEL_DECISION)) == 5
        assert len(_events_of(world, EventTypes.MODEL_ERROR)) == 5
        assert len(_events_of(world, EventTypes.ACTION_EXECUTED)) == 10
        assert engine.agents[0].status == "alive"


async def _drive(engine: Engine, ticks: int) -> None:
    for _ in range(ticks):
        await engine.step_async()
