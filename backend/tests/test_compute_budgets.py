"""S33 â€” compute-constrained lineages: five budget kinds, enforced.

The verification is "an agent cannot exceed configured resources", so
each budget kind has a test that spends past its cap and asserts the
refusal â€” and that nothing was deducted when the refusal happened.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.simulation.agent import Agent
from app.simulation.budget import Budget, LimitExceeded
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World


def _world() -> tuple[World, Engine]:
    """A flat 16x16 lot: every move in these tests lands."""
    world = World(
        "s33",
        16,
        16,
        terrain=[[Terrain.FLOOR] * 16 for _ in range(16)],
    )
    engine = Engine(world, population_id=1)
    engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
    return world, engine


class TestTheLedger:
    def test_spending_within_a_cap_is_recorded(self):
        budget = Budget(limits={"actions": 3})

        budget.spend("actions")

        assert budget.spent["actions"] == 1
        assert budget.remaining("actions") == 2

    def test_an_uncapped_kind_is_unlimited(self):
        budget = Budget()

        assert budget.remaining("actions") is None
        assert budget.can_afford("actions", 10_000)

    def test_a_spend_past_the_cap_is_refused_and_deducts_nothing(self):
        budget = Budget(limits={"actions": 2})
        budget.spend("actions")

        with pytest.raises(LimitExceeded) as excinfo:
            budget.spend("actions", 5)

        assert excinfo.value.kind == "actions"
        assert excinfo.value.amount == 5
        assert excinfo.value.remaining == 1
        assert budget.spent["actions"] == 1  # a budget that lies is worse than none

    def test_negative_caps_and_values_are_refused(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            Budget(limits={"actions": -1})
        budget = Budget()
        with pytest.raises(ValueError, match="must be a number"):
            budget.spend("actions", "many")
        with pytest.raises(ValueError, match="unknown budget kind"):
            budget.spend("magic")

    def test_the_ledger_reports_every_kind(self):
        budget = Budget(limits={"actions": 4, "model_calls": None})
        budget.spend("actions", 2)

        view = budget.to_dict()

        assert view["actions"] == {"spent": 2, "cap": 4, "remaining": 2}
        assert view["model_calls"] == {"spent": 0, "cap": None, "remaining": None}


class TestTheActionBudget:
    def test_an_agent_out_of_actions_is_refused(self):
        world, engine = _world()
        world.set_budget(1, actions=2)

        first = world.execute_action(1, {"action": "look"})
        second = world.execute_action(1, {"action": "look"})
        third = world.execute_action(1, {"action": "look"})

        assert first.ok and second.ok
        assert third.ok is False
        assert third.reason == "action_budget_exceeded"
        assert third.data["remaining"] == 0
        # The spend was refused, not deducted past the cap.
        assert world.budget_of(1).spent["actions"] == 2

    def test_an_action_budget_binds_every_move(self):
        world, engine = _world()
        world.set_budget(1, actions=1)

        moved = world.execute_action(1, {"action": "move", "direction": "east"})
        again = world.execute_action(1, {"action": "move", "direction": "west"})

        assert moved.ok, moved.reason
        assert again.reason == "action_budget_exceeded"

    def test_without_a_budget_actions_are_unlimited(self):
        world, engine = _world()

        for _ in range(25):
            assert world.execute_action(1, {"action": "look"}).ok


class TestTheExperimentBudget:
    def test_the_experiments_ceiling_binds_every_agent(self):
        world, engine = _world()
        for spot in ((2, 6), (3, 7)):
            engine.spawn_agent(
                Agent(agent_id=len(engine.agents) + 1, policy=WanderPolicy()),
                Position(*spot),
            )
        engine.budget = Budget(limits={"actions": 3})
        world._experiment_budget = engine.budget

        world.execute_action(1, {"action": "look"})
        world.execute_action(2, {"action": "look"})
        world.execute_action(3, {"action": "look"})
        out_of_actions = world.execute_action(1, {"action": "look"})

        assert out_of_actions.reason == "action_budget_exceeded"
        assert engine.budget.spent["actions"] == 3


class TestTheThinkingBudgets:
    """Model minds: no call, no tokens, no CPU means no thinking."""


class _StubPolicy:
    """A stub async mind: it thinks only through ``refresh``.
    ``decide`` exists because a budget-refused mind falls back to its
    synchronous decision â€” the fallback path must be complete, not a
    landmine.
    """
    def __init__(self) -> None:
        self.refresh = self._refresh
        self.calls = 0
        self.last_response = None
    async def _refresh(self, observation):
        self.calls += 1
        return {"action": {"action": "look"}}
    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "look"}}
    def _model_world(self, **limits):
        import asyncio
        world = World.generate("s33-model", 16, 16)
        engine = Engine(world, population_id=1)
        policy = _StubPolicy()
        agent = Agent(agent_id=1, policy=policy)
        engine.spawn_agent(agent, Position(2, 2))
        world.set_budget(1, **limits)
        return world, engine, policy
    def test_a_mind_out_of_calls_acts_on_its_fallback(self):
        import asyncio
        world, engine, policy = self._model_world(model_calls=0)
        asyncio.run(engine.step_async())
        assert policy.calls == 0  # it never thought
        exhausted = [
            e for e in world.events if e.type == EventTypes.BUDGET_EXHAUSTED
        ]
        assert len(exhausted) == 1
        assert exhausted[0].actor_id == 1
    def test_each_call_is_charged(self):
        import asyncio
        world, engine, policy = self._model_world(model_calls=2)
        asyncio.run(engine.step_async())
        asyncio.run(engine.step_async())
        assert policy.calls == 2
        assert world.budget_of(1).spent["model_calls"] == 2
        # The third tick cannot think, and says so.
        asyncio.run(engine.step_async())
        assert policy.calls == 2
        assert world.budget_of(1).remaining("model_calls") == 0
    def test_cpu_is_charged_per_thought(self):
        import asyncio
        world, engine, policy = self._model_world(model_calls=2, cpu_seconds=10)
        asyncio.run(engine.step_async())
        spent = world.budget_of(1).spent["cpu_seconds"]
        assert spent > 0
        assert world.budget_of(1).remaining("cpu_seconds") <= 10
    def test_tokens_follow_the_policys_report(self):
        import asyncio
        class _Reporting(self._StubPolicy):
            async def refresh(self, observation):
                self.calls += 1
                self.last_response = type("R", (), {"usage": {"total_tokens": 42}})()
                return {"action": {"action": "look"}}
        world = World.generate("s33-tokens", 16, 16)
        engine = Engine(world, population_id=1)
        policy = _Reporting()
        engine.spawn_agent(Agent(agent_id=1, policy=policy), Position(2, 2))
        world.set_budget(1, tokens=50)
        asyncio.run(engine.step_async())
        assert world.budget_of(1).spent["tokens"] == 42
        assert world.budget_of(1).remaining("tokens") == 8
class TestObservationAndAPI:
    def test_a_mind_sees_its_remaining_budget(self):
        world, engine = _world()
        world.set_budget(1, actions=5)
        observation = engine.agents[0].observe()["budget"]
        assert observation["actions"]["remaining"] == 5
    def test_a_spawn_rule_can_bound_its_members(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'api.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        application = FastAPI()
        application.include_router(health_router, prefix="/api")
        application.include_router(worlds_router, prefix="/api")
        application.state.worlds = WorldRegistry(
            sessionmaker(bind=engine, expire_on_commit=False)
        )
        with TestClient(application) as client:
            world = client.post(
                "/api/worlds",
                json={
                    "seed": "s33",
                    "autostart": False,
                    "populations": [
                        {"name": "frugal", "members": 2, "actions": 3}
                    ],
                    "compute_budget": {"model_calls": 10},
                },
            ).json()
            first = client.get(f"/api/worlds/{world['id']}/agents/1").json()
            assert first["compute"]["budget"]["actions"]["remaining"] == 3
            second = client.get(f"/api/worlds/{world['id']}/agents/2").json()
            assert second["compute"]["budget"]["actions"]["remaining"] == 3
            # The experiment's own ceiling is visible to members.
            assert first["compute"]["budget"]["experiment"]["model_calls"]["cap"] == 10
