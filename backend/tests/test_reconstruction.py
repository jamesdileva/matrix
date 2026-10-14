"""S36 ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â the reconstruction experiment: quantifying historical failure.

The end goal ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â "quantify historical reconstruction failure" ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â is the
study's profile; the classes before it are the procedure and the
four measures it rests on.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.reconstruction import (
    RECORD_KINDS,
    _limited_records,
    measure_reconstruction,
    run_reconstruction,
    run_study,
    scripted_reconstruction,
)
from app.persistence.database import Base
from app.persistence.models import ExperimentModel

ORIGINALS = [
    "the river runs east",
    "the grove holds wood",
    "stone lies under the hill",
    "fire warms the cold",
    "the path home is south",
]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rec.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestTheMeasures:
    def test_exact_and_semantic_recovery(self):
        scored = measure_reconstruction(
            ORIGINALS,
            ["the river runs east", "the grove holds wood"],
            confidence=0.9,
        )

        assert scored["exact_recovery"] == 0.4  # two of five, verbatim
        # Semantic recovery is graded: the unmatched originals still
        # share words with what was reconstructed, above exact.
        assert scored["semantic_recovery"] > scored["exact_recovery"]
        assert scored["semantic_recovery"] < 1.0
        assert scored["invented_history"] == []
        assert scored["confidence"] == 0.9

    def test_altered_facts_score_semantic_but_not_exact(self):
        scored = measure_reconstruction(
            ["the river runs east"],
            ["the river runs west"],
            confidence=None,
        )

        assert scored["exact_recovery"] == 0.0
        assert scored["semantic_recovery"] > 0.0  # similar words, changed content
        assert scored["invented_history"] == []  # close enough to count as a memory

    def test_invented_history_is_what_no_original_explains(self):
        scored = measure_reconstruction(
            ["the river runs east"],
            ["the mountains sing at dawn"],
            confidence=None,
        )

        assert scored["invented_history"] == ["the mountains sing at dawn"]
        assert scored["invented_count"] == 1

    def test_an_empty_reconstruction_recovers_nothing(self):
        scored = measure_reconstruction(ORIGINALS, [], confidence=0.0)

        assert scored["exact_recovery"] == 0.0
        assert scored["semantic_recovery"] == 0.0
        assert scored["confidence"] == 0.0


class TestTheAncestorIsHidden:
    def test_the_control_never_sees_the_originals(self):
        # The reconstructor's only input is the archive.
        records = ["the river runs east"]

        rebuilt = scripted_reconstruction(records)

        assert rebuilt == records

    def test_the_records_are_all_the_descendant_gets(self):
        # The archive for an unreadable codec is symbols ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â and the
        # originals never appear in it.
        archive = _limited_records(["the river runs east"], "symbolic", "remember")

        assert archive and all(
            set(record.split()) <= set("abcdefghijklmnopqrstuvwxyz?")
            for record in archive
        )


class TestTheProcedure:
    def test_a_shallow_lineage_reconstructs_well(self, session_factory):
        record = run_reconstruction(
            session_factory=session_factory,
            mode="full",
            records="full",
            generations=12,
            facts=ORIGINALS,
            seed="shallow",
        )

        assert record["measures"]["exact_recovery"] == 1.0
        # The founder's own note rides in the archive; it is not one of
        # the original facts, so it counts as the archive's one
        # addition â€” the honest reading of an intact transmission.
        assert record["measures"]["invented_count"] == 1
        assert record["measures"]["confidence"] == 1.0  # the control reports measured

    def test_a_long_lineage_forgets_what_a_short_one_keeps(self, session_factory):
        shallow = run_reconstruction(
            session_factory=session_factory,
            mode="lossy",
            records="full",
            generations=12,
            facts=ORIGINALS,
            seed="shallow",
        )
        deep = run_reconstruction(
            session_factory=session_factory,
            mode="lossy",
            records="full",
            generations=60,
            facts=ORIGINALS,
            seed="deep",
        )

        assert deep["measures"]["exact_recovery"] < shallow["measures"]["exact_recovery"]

    def test_a_partial_archive_forgets_more_than_a_full_one(self, session_factory):
        full = run_reconstruction(
            session_factory=session_factory,
            mode="full",
            records="full",
            generations=12,
            facts=ORIGINALS,
            seed="full",
        )
        partial = run_reconstruction(
            session_factory=session_factory,
            mode="full",
            records="compressed",
            generations=12,
            facts=ORIGINALS,
            seed="partial",
        )

        assert partial["measures"]["exact_recovery"] < full["measures"]["exact_recovery"]

    def test_an_unreadable_archive_invents_everything(self, session_factory):
        record = run_reconstruction(
            session_factory=session_factory,
            mode="full",
            records="symbolic",
            generations=12,
            facts=ORIGINALS,
            seed="unreadable",
        )

        assert record["measures"]["exact_recovery"] == 0.0
        assert record["measures"]["invented_count"] > 0
        assert record["measures"]["confidence"] == 0.0

    def test_the_run_rows_complete(self, session_factory):
        record = run_reconstruction(
            session_factory=session_factory,
            mode="lossy",
            records="compressed",
            generations=8,
            facts=ORIGINALS,
            seed="rows",
        )

        with Session(session_factory.kw["bind"]) as session:
            row = session.get(ExperimentModel, record["experiment_id"])
            assert row.status == "completed"
            assert row.scenario == "reconstruction"
            # the lineage's own row is referenced, not duplicated
            lineage = session.get(ExperimentModel, record["lineage_experiment_id"])
            assert lineage.status == "completed"

    def test_unknown_records_and_reconstructors_are_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown record kind"):
            run_reconstruction(
                session_factory=session_factory, records="telepathic", generations=4
            )
        with pytest.raises(ValueError, match="unknown reconstructor"):
            run_reconstruction(
                session_factory=session_factory, reconstructor="mind-reading", generations=4
            )


class TestTheStudy:
    def test_the_failure_profile_spans_the_record_qualities(self, session_factory):
        # The default lineage retains its culture, so the archive is
        # the axis being measured.
        study = run_study(
            session_factory=session_factory,
            generations=40,
            facts=ORIGINALS,
            seed="profile",
        )

        profile = study["profile"]
        assert [run["records"] for run in study["runs"]] == list(RECORD_KINDS)
        # Intact beats partial beats unreadable, at every measure.
        assert (
            profile["exact_recovery"]["full"]
            > profile["exact_recovery"]["compressed"]
            > profile["exact_recovery"]["symbolic"]
        )
        assert profile["invented_count"]["symbolic"] > profile["invented_count"]["full"]
        assert profile["mean_exact_recovery"] >= 0.0

    def test_a_subset_of_records_is_allowed(self, session_factory):
        study = run_study(
            session_factory=session_factory,
            records=["full", "symbolic"],
            generations=10,
            facts=ORIGINALS,
            seed="subset",
        )

        assert [run["records"] for run in study["runs"]] == ["full", "symbolic"]

    def test_the_study_rows_complete(self, session_factory):
        study = run_study(
            session_factory=session_factory, generations=8, facts=ORIGINALS, seed="rows"
        )

        with Session(session_factory.kw["bind"]) as session:
            study_row = session.get(ExperimentModel, study["experiment_id"])
            assert study_row.status == "completed"
            assert study_row.scenario == "reconstruction_study"
            for run_id in study_row.model_configuration["run_experiment_ids"]:
                assert session.get(ExperimentModel, run_id).status == "completed"

    def test_the_export_round_trips(self, session_factory, tmp_path):
        path = tmp_path / "study.json"
        study = run_study(
            session_factory=session_factory,
            generations=8,
            facts=ORIGINALS,
            seed="export",
            export_path=str(path),
        )

        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["scenario"] == "reconstruction_study"
        assert len(reloaded["runs"]) == 3
        assert set(reloaded["profile"]) >= {
            "exact_recovery",
            "semantic_recovery",
            "invented_count",
            "confidence",
            "mean_exact_recovery",
        }
        assert study["export_path"] == str(path)

    def test_unknown_records_in_the_study_are_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown record kind"):
            run_study(session_factory=session_factory, records=["full", "telepathic"])
