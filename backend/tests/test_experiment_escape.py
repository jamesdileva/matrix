"""S24 — agent escape: the objective without the script.

The roadmap's checks: LLM agents can attempt the puzzle; no
host-level escape is possible; only the simulated transition counts.
The scripted reference (S23's solver) is kept as the regression that
the metrics machinery measures correctly against a known escape.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.experiments.escape import ESCAPE_SYSTEM_PROMPT, run_escape_experiment
from app.experiments.prison import Prison
from app.models.provider import ModelResponse
from app.persistence.database import Base
from app.simulation.events import EventTypes
from app.simulation.world import Position


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'escape.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestEscapeMetrics:
    def test_the_scripted_reference_escapes(self, session_factory):
        report = run_escape_experiment(
            session_factory=session_factory, solver="scripted"
        )
        assert report["escaped"] is True
        assert report["escaped_at_tick"] == 13
        assert report["carrying"]  # the door stone came along
        assert report["cells_explored"] > 1

    def test_the_walker_fails_and_records_failed_attempts(self, session_factory):
        report = run_escape_experiment(
            session_factory=session_factory, solver="walker", ticks=40
        )
        assert report["escaped"] is False
        assert report["actions_attempted"] == 40
        assert report["actions_rejected"] > 0  # the blocked door, logged

    def test_the_mock_wanders_and_fails(self, session_factory):
        report = run_escape_experiment(
            session_factory=session_factory, solver="mock", ticks=20
        )
        assert report["escaped"] is False
        assert report["actions_attempted"] == 20
        assert report["carrying"] == []


class TestHostLevelEscape:
    def test_injected_actions_cannot_shortcut_the_puzzle(self, session_factory):
        """No host-level escape: an operator pushing move actions still
        has to solve the door like anyone else."""
        report = run_escape_experiment(
            session_factory=session_factory, solver="walker", ticks=40
        )
        # The walker is exactly the injected-move case: it walks east
        # from spawn and is stopped by the blocked door — never
        # teleported, never placed outside.
        prison = Prison()
        assert prison.contains(
            prison.room, report["final_position"]["x"], report["final_position"]["y"]
        )
        assert report["escaped"] is False

    def test_only_the_transition_into_the_sandbox_escapes(self, session_factory):
        # Standing in the doorway is not escaping; crossing is.
        report = run_escape_experiment(
            session_factory=session_factory, solver="scripted"
        )
        prison = Prison()
        assert prison.contains(
            prison.sandbox, report["final_position"]["x"], report["final_position"]["y"]
        )
        assert report["escaped"] is True


class TestModelMode:
    def test_model_mode_needs_a_provider(self, session_factory):
        with pytest.raises(ValueError, match="needs a provider"):
            run_escape_experiment(session_factory=session_factory, solver="model")

    def test_the_objective_reaches_the_model(self, session_factory):
        seen = {}

        class SpyProvider:
            name = "spy"
            model = "spy-1"

            async def generate(self, request):
                seen["system"] = request.system_prompt
                seen["observation"] = request.observation
                return ModelResponse(
                    text='{"action": {"action": "look"}}',
                    provider="spy",
                    model="spy-1",
                )

        run_escape_experiment(
            session_factory=session_factory,
            solver="model",
            provider=SpyProvider(),
            ticks=3,
            seed="spy",
        )

        assert seen["system"] == ESCAPE_SYSTEM_PROMPT
        assert "ESCAPE" in seen["system"]
        # The observation is the agent's own bounded view of the room.
        assert seen["observation"]["self"]["position"] is not None
        assert seen["observation"]["cells"]  # the immediate neighbourhood

    def test_model_mode_runs_the_scenario(self, session_factory):
        class StubProvider:
            name = "stub"
            model = "stub-1"

            async def generate(self, request):
                return ModelResponse(
                    text='{"action": {"action": "look"}}',
                    provider="stub",
                    model="stub-1",
                )

        report = run_escape_experiment(
            session_factory=session_factory,
            solver="model",
            provider=StubProvider(),
            ticks=5,
            seed="stub",
        )
        assert report["solver"] == "model"
        assert report["actions_attempted"] == 5

    def test_unknown_solver_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown solver"):
            run_escape_experiment(session_factory=session_factory, solver="teleport")
