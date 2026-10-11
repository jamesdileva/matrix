"""S25 — cooperative escape: one body holds one plate, so one body
cannot escape.

The roadmap's checks: a single agent cannot complete the puzzle;
multiple cooperating scripted agents can; the communication between
them is logged.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.coop_escape import build_coop_prison, run_coop_escape_experiment
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.events import EventTypes
from app.simulation.world import Position


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'coop.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestTheCooperativePuzzle:
    def test_the_door_stone_is_too_heavy_to_carry(self):
        from app.simulation.agent import Agent
        from app.simulation.engine import Engine
        from app.simulation.policies import WanderPolicy

        world, prison = build_coop_prison()
        engine = Engine(world)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(10, 7))
        blocker = world.object_at(Position(*prison.door))

        assert blocker is not None and blocker.type == "stone"
        assert blocker.properties.get("heavy") is True

        result = world.execute_action(1, {"action": "pick_up", "object_id": blocker.id})
        assert not result.ok
        assert result.reason == "too_heavy"

    def test_a_solo_agent_cannot_complete_the_puzzle(self, session_factory):
        report = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=1
        )

        assert report["escaped"] is False
        assert report["door_opened_at_tick"] is None
        # The lone agent stands on its plate forever: one body, one plate.
        events = _world_events(session_factory, report)
        assert not [e for e in events if e.type == EventTypes.DOOR_OPENED]


class TestCooperativeEscape:
    def test_the_pair_escapes_together(self, session_factory):
        report = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=2
        )

        assert report["escaped"] is True
        assert report["door_opened_at_tick"] is not None
        # Both halves of the pair cross into the sandbox.
        prison_positions = report["final_positions"]
        assert len(prison_positions) == 2
        from app.experiments.coop_escape import CoopPrison

        prison = CoopPrison()
        for position in prison_positions.values():
            assert prison.contains(prison.sandbox, position["x"], position["y"])

    def test_the_door_requires_joint_occupancy(self, session_factory):
        report = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=2
        )

        events = _world_events(session_factory, report)
        opened = [e for e in events if e.type == EventTypes.DOOR_OPENED]
        assert len(opened) == 1
        assert opened[0].payload["plates"] == [[10, 5], [10, 9]]

    def test_the_communication_is_logged(self, session_factory):
        report = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=2
        )

        assert report["communication_events"] == 2
        assert report["messages"] == [
            "agent 1 is on my plate",
            "agent 2 is on my plate",
        ]

    def test_teammates_appear_in_observations(self, session_factory):
        world, prison = build_coop_prison()
        from app.simulation.agent import Agent
        from app.simulation.engine import Engine
        from app.simulation.policies import WanderPolicy

        engine = Engine(world)
        first = Agent(agent_id=1, policy=WanderPolicy())
        second = Agent(agent_id=2, policy=WanderPolicy())
        engine.spawn_agent(first, Position(*prison.spawns[0]))
        engine.spawn_agent(second, Position(*prison.spawns[1]))
        world.add_to_team(1, 1)
        world.add_to_team(2, 1)

        observation = first.observe()

        assert observation["teammates"] == [
            {"id": 2, "position": {"x": 4, "y": 5}}
        ]
        assert second.observe()["teammates"] == [
            {"id": 1, "position": {"x": 4, "y": 3}}
        ]

    def test_the_run_is_deterministic(self, session_factory):
        first = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=2, seed="same"
        )
        second = run_coop_escape_experiment(
            session_factory=session_factory, solver="scripted", agents=2, seed="same"
        )
        assert first["escaped_at_tick"] == second["escaped_at_tick"]
        assert first["final_positions"] == second["final_positions"]


class TestModelMode:
    def test_model_mode_requires_a_provider(self, session_factory):
        with pytest.raises(ValueError, match="needs a provider"):
            run_coop_escape_experiment(session_factory=session_factory, solver="model")

    def test_unknown_solver_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown solver"):
            run_coop_escape_experiment(session_factory=session_factory, solver="teleport")


def _world_events(session_factory, report):
    from sqlalchemy.orm import Session

    from app.persistence.models import EventModel

    with Session(session_factory.kw["bind"]) as session:
        experiment = session.get(ExperimentModel, report["experiment_id"])
        return (
            session.query(EventModel)
            .filter_by(world_id=experiment.world_id)
            .order_by(EventModel.id)
            .all()
        )
