"""S11 — the 100-generation lineage experiment.

Scripted calibrations produce *known* transmission phenomena, so the
metrics are checked against ground truth rather than smoke-tested. The
model mode is exercised with a stub provider that decides inheritance
over the refresh path.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.lineage import (
    DEFAULT_FACTS,
    DEFAULT_GENERATIONS,
    export_report,
    replay_lineage_experiment,
    run_lineage_experiment,
)
from app.persistence.database import Base
from app.persistence.models import AgentModel, ExperimentModel
from app.simulation.events import EventTypes


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'experiment.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class StubProvider:
    """A provider whose decisions carry inheritance (the model path)."""

    name = "stub"
    model = "stub-1"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request):
        from app.models.provider import ModelResponse

        self.calls += 1
        knowledge = request.observation.get("knowledge", [])
        return ModelResponse(
            text=json.dumps(
                {
                    "action": {"action": "look"},
                    "inheritance": {
                        "traits": {},
                        "knowledge": knowledge,
                        "message": f"stub generation {self.calls}",
                        "cultural_artifacts": [],
                    },
                }
            ),
            provider=self.name,
            model=self.model,
        )


def _run(session_factory, mode, generations=DEFAULT_GENERATIONS):
    return run_lineage_experiment(
        session_factory=session_factory, mode=mode, generations=generations, seed=f"s-{mode}"
    )


class TestRoadmapVerification:
    def test_experiment_completes_without_manual_intervention(self, session_factory):
        report = _run(session_factory, "full")

        assert report["generations"] == DEFAULT_GENERATIONS
        assert report["experiment_id"] is not None
        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, report["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.started_at is not None
            assert experiment.finished_at is not None
            assert experiment.generation_limit == DEFAULT_GENERATIONS
            assert experiment.scenario == "lineage_100gen"
            # The controlled knowledge set is recorded with the run.
            assert experiment.model_configuration["facts"] == list(DEFAULT_FACTS)

    def test_every_generation_exists(self, session_factory):
        report = _run(session_factory, "full")

        assert [entry["generation"] for entry in report["trajectory"]] == list(
            range(1, DEFAULT_GENERATIONS + 1)
        )
        with Session(session_factory.kw["bind"]) as session:
            agents = session.query(AgentModel).all()
            generations = sorted(a.generation for a in agents)
            assert generations == list(range(DEFAULT_GENERATIONS + 1))  # founder + 100
            born = session.query(ExperimentModel).count()
        assert born == 1

    def test_model_mode_runs_through_the_refresh_path(self, session_factory, monkeypatch):
        provider = StubProvider()
        monkeypatch.setattr(
            "app.experiments.lineage.provider_from_settings", lambda config=None: provider
        )
        report = run_lineage_experiment(
            session_factory=session_factory, mode="model", generations=25, seed="s-model"
        )

        assert report["generations"] == 25
        assert provider.calls == 25  # one refresh per generation
        assert report["totals"]["retained_facts"] == len(DEFAULT_FACTS)


class TestMetrics:
    def test_control_retains_everything(self, session_factory):
        report = _run(session_factory, "full")

        assert report["totals"]["retained_facts"] == 10
        assert report["totals"]["lost_facts"] == 0
        assert report["totals"]["new_facts"] == 0
        assert report["totals"]["altered_facts"] == 0
        assert report["final"]["avg_similarity"] == 1.0  # verbatim, always
        assert all(entry["message_length"] > 0 for entry in report["trajectory"])

    def test_lossy_policy_loses_facts_on_a_staircase(self, session_factory):
        report = _run(session_factory, "lossy")

        # One fact dropped per 10 generations: 10 drops over 100.
        assert report["totals"]["lost_facts"] == 10
        assert report["totals"]["retained_facts"] == 0
        retained_over_time = [len(entry["retained"]) for entry in report["trajectory"]]
        assert retained_over_time[0] == 10  # generation 1: nothing lost yet
        assert retained_over_time[9] == 9  # generation 10: first drop
        assert retained_over_time[-1] == 0  # generation 100: all of them

    def test_altering_policy_produces_altered_facts(self, session_factory):
        report = _run(session_factory, "altering")

        assert report["totals"]["altered_facts"] == 10  # every fact re-worded once
        assert report["totals"]["retained_facts"] == 0
        assert report["totals"]["contradicted_facts"] == 0  # altered, not negated
        final_altered = report["final"]["altered"]
        assert all(fact.startswith("it is said that ") for fact in final_altered)

    def test_negating_policy_produces_contradictions(self, session_factory):
        report = _run(session_factory, "negating")

        assert report["totals"]["contradicted_facts"] == 10
        assert all(
            any(token in fact.split() for token in ("not",))
            for fact in report["final"]["contradicted"]
        )

    def test_new_facts_are_additions(self, session_factory):
        report = _run(session_factory, "new")

        assert report["totals"]["new_facts"] == 10
        assert report["totals"]["retained_facts"] == 10  # originals still pass too
        assert report["final"]["facts_received"] == 20

    def test_message_lengths_are_measured(self, session_factory):
        report = _run(session_factory, "lossy")

        lengths = [entry["message_length"] for entry in report["trajectory"]]
        assert all(length > 0 for length in lengths)
        assert report["totals"]["avg_message_length"] > 0


class TestReplayAndExport:
    def test_replay_rebuilds_the_chain_from_events(self, session_factory):
        report = _run(session_factory, "full", generations=25)

        replay = replay_lineage_experiment(session_factory, report["experiment_id"])

        assert replay["chain_length"] == 25
        assert [entry["generation"] for entry in replay["generations"]] == list(range(1, 26))
        assert replay["originals"] == list(DEFAULT_FACTS)
        assert replay["mode"] == "full"
        # Every generation records exactly what it received.
        assert replay["generations"][-1]["inheritance"]["knowledge"] == list(DEFAULT_FACTS)

    def test_export_writes_valid_json(self, session_factory, tmp_path):
        report = _run(session_factory, "full", generations=10)

        path = tmp_path / "report.json"
        export_report(report, str(path))

        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["generations"] == 10
        assert loaded["totals"] == report["totals"]

    def test_unknown_experiment_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown experiment"):
            replay_lineage_experiment(session_factory, 999)

    def test_unknown_mode_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_lineage_experiment(session_factory=session_factory, mode="telepathy", generations=2)
