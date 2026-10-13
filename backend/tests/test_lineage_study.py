"""S32 — multiple independent lineages: the study and its measures.

The sprint's verification — "results are exportable and statistically
comparable" — is the export and statistics sections; the measure
sections are the roadmap's list, each asserted for what it must show.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.lineage_study import (
    STUDY_SCENARIO,
    compare_runs,
    export_study,
    run_study,
)
from app.persistence.database import Base
from app.persistence.models import ExperimentModel

FOUNDER_FACTS = [
    "the river runs east",
    "the grove holds wood",
    "stone lies under the hill",
    "fire warms the cold",
]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'study.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestTheStudy:
    def test_identical_starts_and_seeds_converge_completely(self, session_factory):
        """The null hypothesis: same seed, same mind, same history."""
        study = run_study(
            session_factory=session_factory,
            runs=3,
            mode="full",
            generations=10,
            facts=FOUNDER_FACTS,
            seed="null",
        )

        comparison = study["comparison"]
        assert comparison["cultural_convergence"]["facts"] == 1.0
        assert comparison["divergence"]["facts"] == 0.0
        assert comparison["information_loss"]["mean"] == 0.0
        assert comparison["strategies"]["profile_spread"] == 0.0

    def test_the_same_study_is_deterministic(self, session_factory):
        first = run_study(
            session_factory=session_factory, runs=2, mode="lossy", generations=8,
            facts=FOUNDER_FACTS, seed="repeat",
        )
        second = run_study(
            session_factory=session_factory, runs=2, mode="lossy", generations=8,
            facts=FOUNDER_FACTS, seed="repeat",
        )

        assert first["comparison"] == second["comparison"]
        assert [r["knowledge_final"] for r in first["run_records"]] == [
            r["knowledge_final"] for r in second["run_records"]
        ]

    def test_different_minds_diverge(self, session_factory):
        study = run_study(
            session_factory=session_factory,
            runs=3,
            vary="model",
            models=["full", "lossy", "new"],
            generations=12,
            facts=FOUNDER_FACTS,
            seed="minds",
        )

        comparison = study["comparison"]
        # The founder's facts are the constant; the minds are the axis.
        assert comparison["cultural_convergence"]["facts"] < 1.0
        assert comparison["divergence"]["facts"] > 0
        assert comparison["information_loss"]["mean"] > 0
        assert [run["mode"] for run in study["runs"]] == ["full", "lossy", "new"]
        # The lossy run loses what the full run keeps.
        losses = {run["mode"]: run["information_loss"] for run in study["runs"]}
        assert losses["full"] == 0.0
        assert losses["lossy"] > 0

    def test_every_run_gets_its_own_experiment_row(self, session_factory):
        study = run_study(
            session_factory=session_factory, runs=3, mode="lossy", generations=6,
            facts=FOUNDER_FACTS, seed="rows",
        )

        with Session(session_factory.kw["bind"]) as session:
            study_row = session.get(ExperimentModel, study["experiment_id"])
            assert study_row.status == "completed"
            assert study_row.scenario == STUDY_SCENARIO
            run_ids = study_row.model_configuration["run_experiment_ids"]
            assert len(run_ids) == 3
            for run_id in run_ids:
                assert session.get(ExperimentModel, run_id).status == "completed"


class TestTheMeasures:
    def test_convergence_is_one_for_identical_cultures(self):
        runs = [{"knowledge_final": ["a", "b"], "vocabulary": ["a"], "profile": {"retained": 1.0, "altered": 0.0, "contradicted": 0.0, "new": 0.0}, "information_loss": 0.0, "seed": "s"}]

        comparison = compare_runs(runs, ["a", "b"])

        assert comparison["cultural_convergence"]["facts"] == 1.0
        assert comparison["divergence"]["facts"] == 0.0

    def test_divergence_counts_what_only_one_run_knows(self):
        runs = [
            {"knowledge_final": ["a", "b"], "vocabulary": ["a", "b"], "profile": {"retained": 0.5, "altered": 0.0, "contradicted": 0.0, "new": 0.5}, "information_loss": 0.0, "seed": "one"},
            {"knowledge_final": ["a", "c"], "vocabulary": ["a", "c"], "profile": {"retained": 0.5, "altered": 0.0, "contradicted": 0.0, "new": 0.5}, "information_loss": 0.0, "seed": "two"},
        ]

        comparison = compare_runs(runs, ["a", "b"])

        assert comparison["divergence"]["facts"] == round(1 - 1 / 3, 4)
        assert comparison["divergence"]["unique_facts_per_run"]["mean"] == 1.0
        assert comparison["vocabulary"]["union"] == 3
        assert comparison["vocabulary"]["shared"] == 1

    def test_information_loss_has_statistics(self):
        runs = [
            {"knowledge_final": ["a"], "vocabulary": [], "profile": {"retained": 1.0, "altered": 0.0, "contradicted": 0.0, "new": 0.0}, "information_loss": 0.0, "seed": "s1"},
            {"knowledge_final": [], "vocabulary": [], "profile": {"retained": 0.0, "altered": 0.0, "contradicted": 0.0, "new": 0.0}, "information_loss": 0.5, "seed": "s2"},
        ]

        loss = compare_runs(runs, ["a", "b"])["information_loss"]

        assert loss["n"] == 2
        assert loss["mean"] == 0.25
        assert loss["stdev"] == 0.25
        assert loss["min"] == 0.0
        assert loss["max"] == 0.5

    def test_strategies_report_the_consensus_and_the_spread(self):
        retentive = {"retained": 1.0, "altered": 0.0, "contradicted": 0.0, "new": 0.0}
        inventive = {"retained": 0.0, "altered": 0.0, "contradicted": 0.0, "new": 1.0}
        runs = [
            {"knowledge_final": ["a"], "vocabulary": [], "profile": retentive, "information_loss": 0.0, "seed": "s1"},
            {"knowledge_final": ["z"], "vocabulary": [], "profile": inventive, "information_loss": 0.0, "seed": "s2"},
        ]

        strategies = compare_runs(runs, ["a"])["strategies"]

        assert strategies["per_run"][0]["dominant"] == "retained"
        assert strategies["per_run"][1]["dominant"] == "new"
        assert strategies["consensus_profile"]["retained"] == 0.5
        assert strategies["profile_spread"] == 1.0  # opposite strategies, maximally far


class TestTheExport:
    def test_the_study_export_is_complete_json(self, session_factory, tmp_path):
        study = run_study(
            session_factory=session_factory, runs=2, mode="lossy", generations=8,
            facts=FOUNDER_FACTS, seed="export",
        )
        path = tmp_path / "out" / "study.json"

        written = export_study(study, str(path))

        assert path.exists()
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["scenario"] == STUDY_SCENARIO
        assert reloaded["originals"] == FOUNDER_FACTS
        assert len(reloaded["runs"]) == 2
        assert set(reloaded["comparison"]) >= {
            "cultural_convergence",
            "divergence",
            "information_loss",
            "strategies",
            "vocabulary",
        }
        assert written == str(path)

    def test_the_cli_writes_what_it_says(self, session_factory, tmp_path):
        from app.experiments import lineage_study

        path = tmp_path / "cli.json"
        study = lineage_study.run_study(
            session_factory=session_factory,
            runs=1,
            mode="full",
            generations=4,
            facts=FOUNDER_FACTS,
            seed="cli",
            export_path=str(path),
        )

        assert study["export_path"] == str(path)
        assert json.loads(path.read_text(encoding="utf-8"))["comparison"]["runs"] == 1


class TestBadRequests:
    def test_a_study_needs_runs(self, session_factory):
        with pytest.raises(ValueError, match="at least one run"):
            run_study(session_factory=session_factory, runs=0)

    def test_varying_the_mind_needs_one_mode_per_run(self, session_factory):
        with pytest.raises(ValueError, match="one mode per run"):
            run_study(
                session_factory=session_factory, runs=3, vary="model", models=["full", "lossy"]
            )

    def test_an_unknown_axis_is_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown vary axis"):
            run_study(session_factory=session_factory, runs=2, vary="weather")
