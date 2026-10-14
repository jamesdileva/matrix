"""S35 â€” cultural compression: bandwidth, retention, reconstruction.

The end goal â€” "determine whether repeated scarcity encourages
communication efficiency" â€” is the study class; the classes before it
are the codecs and the transmission chain it rests on.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.compression import (
    CODECS,
    Codebook,
    Codec,
    run_compression_lineage,
    run_study,
)
from app.persistence.database import Base
from app.persistence.models import ExperimentModel

FACTS = [
    "the river runs east",
    "the grove holds wood",
    "stone lies under the hill",
    "fire warms the cold",
    "the path home is south",
]
MESSAGE = "the river runs east, remember the grove and the fire"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'comp.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestTheCodecs:
    def test_verbose_transmits_everything(self):
        codec = CODECS["verbose"]
        book = Codebook()

        assert codec.encode_facts(FACTS, book) == FACTS
        assert codec.encode_message(MESSAGE, book) == MESSAGE
        assert codec.decode_message(MESSAGE, book) == MESSAGE

    def test_compressed_truncates_to_its_bandwidth(self):
        codec = CODECS["compressed"]
        book = Codebook()

        assert len(codec.encode_facts(FACTS, book)) == 3  # fact_bandwidth
        assert len(codec.encode_message(MESSAGE, book).split()) == 6  # token_bandwidth
        assert codec.decode_message(codec.encode_message(MESSAGE, book), book).split() == MESSAGE.split()[:6]

    def test_symbolic_uses_a_shared_dictionary(self):
        codec = CODECS["symbolic"]
        book = Codebook()

        first = codec.encode_message(MESSAGE, book)
        # "the" appears twice, so the first symbol repeats.
        assert first.split()[0] == first.split()[8]
        assert len(set(first.split())) < len(first.split())  # repetition is the point
        # The dictionary is shared: the same token keeps its symbol.
        assert codec.encode_message(MESSAGE, book) == first
        assert book.size == len(set(MESSAGE.split()))

    def test_a_full_dictionary_costs_reconstruction(self):
        codec = Codec("capped", symbolic=True, vocabulary_cap=4)
        book = Codebook()

        encoded = codec.encode_message("the river runs east today", book)
        decoded = codec.decode_message(encoded, book)

        assert "?" in decoded.split()  # tokens past the cap cannot be rebuilt
        assert book.size == 4

    def test_bits_charge_symbols_at_the_codebooks_rate(self):
        codec = CODECS["verbose"]
        book = Codebook()

        # 10 tokens at log2(32) = 5 bits each.
        assert codec.bits(MESSAGE, book, vocabulary_size=32) == 50
        assert codec.bits(MESSAGE, book, vocabulary_size=2) == 10

    def test_symbolic_bits_charge_the_dictionary(self):
        import math

        codec = CODECS["symbolic"]
        book = Codebook()
        codec.encode_message(MESSAGE, book)  # the dictionary learns the words

        bits = codec.bits(MESSAGE, book, 999)

        # Ten symbols, each costing log2 of the shared codebook.
        assert bits == len(MESSAGE.split()) * math.log2(book.size)
        assert bits == 30


class TestTheLineage:
    def test_the_control_loses_nothing(self, session_factory):
        record = run_compression_lineage(
            session_factory=session_factory, codec_name="verbose", generations=8,
            facts=FACTS, message=MESSAGE, seed="control",
        )

        totals = record["totals"]
        assert totals["retention_rate"] == 1.0
        assert totals["final_reconstruction_accuracy"] == 1.0
        assert totals["avg_reconstruction_accuracy"] == 1.0

    def test_a_restricted_bandwidth_costs_knowledge(self, session_factory):
        record = run_compression_lineage(
            session_factory=session_factory, codec_name="compressed", generations=8,
            facts=FACTS, message=MESSAGE, seed="tight",
        )

        totals = record["totals"]
        assert totals["retention_rate"] < 1.0
        assert totals["final_reconstruction_accuracy"] < 1.0
        assert totals["avg_bits_per_generation"] < CODECS["verbose"].bits(
            MESSAGE, Codebook(), 32
        )

    def test_the_symbolic_code_costs_less_than_truncation(self, session_factory):
        compressed = run_compression_lineage(
            session_factory=session_factory, codec_name="compressed", generations=8,
            facts=FACTS, message=MESSAGE, seed="c",
        )
        symbolic = run_compression_lineage(
            session_factory=session_factory, codec_name="symbolic", generations=8,
            facts=FACTS, message=MESSAGE, seed="s",
        )

        # The shared dictionary keeps more of the culture standing than
        # cutting the list does.
        assert symbolic["totals"]["retention_rate"] > compressed["totals"]["retention_rate"]

    def test_the_lineage_is_deterministic(self, session_factory):
        first = run_compression_lineage(
            session_factory=session_factory, codec_name="symbolic", generations=6,
            facts=FACTS, message=MESSAGE, seed="same",
        )
        second = run_compression_lineage(
            session_factory=session_factory, codec_name="symbolic", generations=6,
            facts=FACTS, message=MESSAGE, seed="same",
        )

        assert first["totals"] == second["totals"]
        assert [t["bits_transmitted"] for t in first["trajectory"]] == [
            t["bits_transmitted"] for t in second["trajectory"]
        ]

    def test_unknown_codecs_are_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown codec"):
            run_compression_lineage(session_factory=session_factory, codec_name="telepathy")

    def test_the_run_row_completes(self, session_factory):
        record = run_compression_lineage(
            session_factory=session_factory, codec_name="verbose", generations=4,
            facts=FACTS, message=MESSAGE, seed="row",
        )

        with Session(session_factory.kw["bind"]) as session:
            row = session.get(ExperimentModel, record["experiment_id"])
            assert row.status == "completed"
            assert row.scenario == "compression_lineage"
            assert row.model_configuration["codec"] == "verbose"


class TestTheStudy:
    def test_the_three_transmissions_side_by_side(self, session_factory):
        study = run_study(session_factory=session_factory, generations=10,
                          facts=FACTS, message=MESSAGE, seed="study")

        assert [run["codec"] for run in study["runs"]] == ["verbose", "compressed", "symbolic"]
        comparison = study["comparison"]
        # Scarcity shows up as fewer bits; the costs show up as lost
        # retention and reconstruction. All three columns, together.
        assert comparison["bits_per_generation"]["verbose"] > comparison["bits_per_generation"]["compressed"]
        assert comparison["bits_saved_vs_verbose"]["compressed"] > 0
        assert comparison["bits_saved_vs_verbose"]["symbolic"] > 0
        assert comparison["retention_rate"]["verbose"] == 1.0
        assert comparison["retention_rate"]["compressed"] < 1.0
        assert comparison["reconstruction_accuracy"]["verbose"] == 1.0

    def test_a_subset_of_codecs_is_allowed(self, session_factory):
        study = run_study(session_factory=session_factory, codecs=["verbose", "symbolic"],
                          generations=5, facts=FACTS, message=MESSAGE, seed="subset")

        assert [run["codec"] for run in study["runs"]] == ["verbose", "symbolic"]

    def test_the_study_rows_complete(self, session_factory):
        study = run_study(session_factory=session_factory, generations=4,
                          facts=FACTS, message=MESSAGE, seed="rows")

        with Session(session_factory.kw["bind"]) as session:
            study_row = session.get(ExperimentModel, study["experiment_id"])
            assert study_row.status == "completed"
            assert study_row.scenario == "compression_study"
            for run_id in study_row.model_configuration["run_experiment_ids"]:
                assert session.get(ExperimentModel, run_id).status == "completed"

    def test_the_export_round_trips(self, session_factory, tmp_path):
        path = tmp_path / "study.json"
        study = run_study(session_factory=session_factory, generations=4,
                          facts=FACTS, message=MESSAGE, seed="export",
                          export_path=str(path))

        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["scenario"] == "compression_study"
        assert len(reloaded["runs"]) == 3
        assert set(reloaded["comparison"]) >= {
            "bits_per_generation",
            "retention_rate",
            "reconstruction_accuracy",
            "bits_saved_vs_verbose",
        }
        assert study["export_path"] == str(path)

    def test_unknown_codecs_in_the_study_are_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown codec"):
            run_study(session_factory=session_factory, codecs=["verbose", "telepathy"])
