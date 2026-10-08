"""ModelPolicy: the sync-engine / async-provider bridge, proven safe in a
live world. These tests drive the same loop shape the S08 host will use
(advance the world, refresh each model policy, then let the agent act)
and assert the roadmap's headline guarantee: a broken or hostile brain
can never corrupt world state."""

import asyncio

from app.models.mock import MockProvider
from app.models.provider import ModelResponse, ProviderError
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.world import Position, World

MINIMAL_OBSERVATION = {
    "self": {"id": 1, "position": {"x": 5, "y": 5}, "tick": 0, "goal": None},
    "cells": [{"direction": "here", "position": {"x": 5, "y": 5}, "terrain": "floor"}],
    "nearby": [],
    "inventory": [],
    "messages": [],
}


class ExplodingProvider:
    name = "exploding"

    async def generate(self, request):
        raise ProviderError("brain on fire")


class GarbageProvider:
    name = "garbage"

    async def generate(self, request):
        return ModelResponse(text="I'd rather not.", provider="garbage", model=None)


class GuideShapeProvider:
    """Emits guide §7's {"type": ...} verb spelling."""

    name = "guide_shape"

    async def generate(self, request):
        return ModelResponse(
            text='{"action": {"type": "look"}, "goal_update": "wait"}',
            provider="guide_shape",
            model=None,
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


async def _drive(engine: Engine, ticks: int) -> None:
    """The S08 host-loop shape: world advances, then each model agent
    refreshes its provider before acting. The engine itself never awaits."""
    for _ in range(ticks):
        engine.world.step()
        for agent in engine.agents:
            if isinstance(agent.policy, ModelPolicy):
                await agent.policy.refresh(agent.observe())
            agent.act()


class TestDecidePath:
    def test_stored_decision_returned(self):
        policy = ModelPolicy(MockProvider())
        decision = asyncio.run(policy.refresh(MINIMAL_OBSERVATION))
        assert decision is not None
        assert policy.decide(MINIMAL_OBSERVATION) == decision
        assert policy.last_error is None

    def test_safe_fallback_before_any_refresh(self):
        policy = ModelPolicy(MockProvider())
        assert policy.decide(MINIMAL_OBSERVATION) == {"action": {"action": "look"}}

    def test_provider_error_falls_back_with_reason(self):
        policy = ModelPolicy(ExplodingProvider())
        assert asyncio.run(policy.refresh(MINIMAL_OBSERVATION)) is None
        assert policy.last_error is not None
        assert policy.last_error.startswith("provider_error")
        assert policy.decide(MINIMAL_OBSERVATION) == {"action": {"action": "look"}}

    def test_invalid_output_falls_back_with_reason(self):
        policy = ModelPolicy(GarbageProvider())
        assert asyncio.run(policy.refresh(MINIMAL_OBSERVATION)) is None
        assert policy.last_error is not None
        assert policy.last_error.startswith("invalid_decision")
        assert policy.decide(MINIMAL_OBSERVATION) == {"action": {"action": "look"}}

    def test_guide_shape_normalized_end_to_end(self):
        policy = ModelPolicy(GuideShapeProvider())
        decision = asyncio.run(policy.refresh(MINIMAL_OBSERVATION))
        assert decision == {"action": {"action": "look"}, "goal_update": "wait"}

    def test_custom_fallback_action_respected(self):
        # fallback_action is an action proposal; decide() wraps it in the
        # decision contract the Agent consumes.
        policy = ModelPolicy(GarbageProvider(), fallback_action={"action": "inspect", "object_id": 999})
        assert policy.decide(MINIMAL_OBSERVATION) == {
            "action": {"action": "inspect", "object_id": 999}
        }


class TestWorldSafety:
    def test_failing_provider_never_corrupts_world(self):
        policy = ModelPolicy(ExplodingProvider())
        engine = _spawn_engine(policy)
        start_position = engine.agents[0].position
        start_objects = [obj.to_dict() for obj in engine.world.objects]

        asyncio.run(_drive(engine, ticks=10))

        world = engine.world
        assert world.tick == 10
        assert engine.agents[0].position == start_position  # "look" never moves
        assert [obj.to_dict() for obj in world.objects] == start_objects
        assert world.inventory(1) == ()
        action_events = [
            e for e in world.events if e.type in (EventTypes.ACTION_EXECUTED, EventTypes.ACTION_REJECTED)
        ]
        assert len(action_events) == 10
        assert all(e.type == EventTypes.ACTION_EXECUTED for e in action_events)
        assert all(e.payload["action"] == {"action": "look"} for e in action_events)

    def test_invalid_output_never_corrupts_world(self):
        policy = ModelPolicy(GarbageProvider())
        engine = _spawn_engine(policy)
        start_position = engine.agents[0].position

        asyncio.run(_drive(engine, ticks=5))

        action_events = [e for e in engine.world.events if e.type.startswith("ACTION_")]
        assert len(action_events) == 5
        assert all(e.type == EventTypes.ACTION_EXECUTED for e in action_events)
        assert engine.agents[0].position == start_position

    def test_valid_decisions_are_applied(self):
        policy = ModelPolicy(MockProvider())
        engine = _spawn_engine(policy)

        asyncio.run(_drive(engine, ticks=20))

        action_events = [e for e in engine.world.events if e.type.startswith("ACTION_")]
        assert len(action_events) == 20
        # The mock only proposes actions it saw were legal; the world
        # must never have had to reject one.
        assert all(e.type == EventTypes.ACTION_EXECUTED for e in action_events)
        assert engine.world.tick == 20

    def test_goal_update_from_decision_is_applied(self):
        policy = ModelPolicy(GuideShapeProvider())
        engine = _spawn_engine(policy)

        asyncio.run(_drive(engine, ticks=1))

        assert engine.agents[0].goal == "wait"

    def test_mock_provider_world_runs_deterministically(self):
        engine_a = _spawn_engine(ModelPolicy(MockProvider()))
        engine_b = _spawn_engine(ModelPolicy(MockProvider()))

        asyncio.run(_drive(engine_a, ticks=20))
        asyncio.run(_drive(engine_b, ticks=20))

        assert [e.to_dict() for e in engine_a.world.events] == [
            e.to_dict() for e in engine_b.world.events
        ]
        assert engine_a.world.snapshot() == engine_b.world.snapshot()
