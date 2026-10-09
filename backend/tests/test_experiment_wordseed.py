"""S16 — the word-seed experiment: produced culture, stored and compared.

The control (scripted) must agree across identically-seeded
populations; scatter must diverge deterministically; storage must
show up as world objects, agent rows and timeline events.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.wordseed import run_word_seed_experiment
from app.persistence.database import Base
from app.persistence.models import AgentModel, WorldModel
from app.simulation.events import EventTypes


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'wordseed.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


SEEDS = ["light", "water", "stone"]


class TestScriptedControl:
    def test_identical_seeds_produce_identical_artifacts(self, session_factory):
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=2
        )

        assert report["comparison"]["artifacts_total"] == 6
        assert report["comparison"]["unique_artifacts"] == 3  # one variant per seed
        assert report["comparison"]["identical_seeds"] == sorted(SEEDS)
        assert report["comparison"]["divergent_seeds"] == []
        for seed_word, stats in report["comparison"]["per_seed"].items():
            assert stats["variants"] == 1
            assert stats["concept_jaccard"] == 1.0
            assert stats["identical"] is True

    def test_artifacts_follow_the_guide_shape(self, session_factory):
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=["light"], populations=1
        )

        artifact = report["population_artifacts"][0]["artifacts"][0]
        assert artifact["seed"] == "light"
        assert len(artifact["concepts"]) == 3
        assert artifact["kind"]  # one of the guide's kinds
        assert artifact["title"] and artifact["body"]

    def test_is_deterministic(self, session_factory):
        first = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=2
        )
        second = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=2
        )
        assert [a["artifacts"] for a in first["population_artifacts"]] == [
            a["artifacts"] for a in second["population_artifacts"]
        ]


class TestScatter:
    def test_identical_seeds_diverge_deterministically(self, session_factory):
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scatter", seeds=SEEDS, populations=3
        )

        comparison = report["comparison"]
        assert comparison["artifacts_total"] == 9
        assert comparison["unique_artifacts"] == 9  # every population varies
        assert comparison["identical_seeds"] == []
        assert comparison["divergent_seeds"] == sorted(SEEDS)
        for seed_word, stats in comparison["per_seed"].items():
            assert stats["variants"] == 3

    def test_scatter_is_reproducible(self, session_factory):
        first = run_word_seed_experiment(
            session_factory=session_factory, mode="scatter", seeds=SEEDS, populations=2
        )
        second = run_word_seed_experiment(
            session_factory=session_factory, mode="scatter", seeds=SEEDS, populations=2
        )
        assert first["comparison"] == second["comparison"]


class TestStorage:
    def test_artifacts_are_stored_as_cultural_objects(self, session_factory):
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=1
        )
        world_id = report["population_artifacts"][0]["world_id"]

        with Session(session_factory.kw["bind"]) as session:
            world = session.get(WorldModel, world_id)
            rows = session.query(AgentModel).filter_by(world_id=world_id).all()
            # One agent row per seed, each carrying its artifact.
            assert len(rows) == 3
            for row in rows:
                assert len(row.cultural_artifacts) == 1
                assert row.acquired_knowledge  # the three concepts

    def test_artifact_events_on_the_timeline(self, session_factory):
        from app.persistence.models import EventModel

        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=1
        )
        world_id = report["population_artifacts"][0]["world_id"]

        with Session(session_factory.kw["bind"]) as session:
            events = (
                session.query(EventModel)
                .filter_by(world_id=world_id, type=EventTypes.ARTIFACT_CREATED)
                .all()
            )
        assert len(events) == 3
        assert all(e.payload["artifact"]["kind"] for e in events)

    def test_world_objects_placed_for_artifacts(self, session_factory):
        from app.persistence.models import EventModel

        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=SEEDS, populations=1
        )
        world_id = report["population_artifacts"][0]["world_id"]

        with Session(session_factory.kw["bind"]) as session:
            object_events = (
                session.query(EventModel)
                .filter_by(world_id=world_id, type=EventTypes.OBJECT_CREATED)
                .count()
            )
        assert object_events == 3  # one cultural object per artifact


class TestModelMode:
    def test_model_mode_uses_the_provider_and_parses(self, session_factory, monkeypatch):
        from app.experiments.wordseed import _model_artifact
        from app.models.provider import ModelResponse

        class StubProvider:
            name = "stub"
            model = "stub-1"

            async def generate(self, request):
                return ModelResponse(
                    text=json.dumps(
                        {
                            "concepts": ["glow", "hush", "tide"],
                            "artifact": {
                                "kind": "poem",
                                "title": "the glow tide",
                                "body": "a poem of glow, hush and tide",
                            },
                        }
                    ),
                    provider="stub",
                    model="stub-1",
                )

        monkeypatch.setattr(
            "app.experiments.wordseed.provider_from_settings",
            lambda config=None: StubProvider(),
        )
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="model", seeds=["light", "water"], populations=2
        )

        artifacts = [a for p in report["population_artifacts"] for a in p["artifacts"]]
        assert len(artifacts) == 4
        assert all(a["concepts"] == ["glow", "hush", "tide"] for a in artifacts)
        assert all(a["kind"] == "poem" for a in artifacts)
        # Identical model responses across populations — the comparison
        # machinery reports that correctly.
        assert report["comparison"]["identical_seeds"] == ["light", "water"]

    def test_model_output_failure_is_loud(self, session_factory, monkeypatch):
        from app.models.provider import ModelResponse

        class GarbageProvider:
            name = "garbage"
            model = "garbage-1"

            async def generate(self, request):
                return ModelResponse(text="I'd rather not.", provider="garbage", model=None)

        monkeypatch.setattr(
            "app.experiments.wordseed.provider_from_settings",
            lambda config=None: GarbageProvider(),
        )
        with pytest.raises(ValueError, match="not usable"):
            run_word_seed_experiment(
                session_factory=session_factory, mode="model", seeds=["light"], populations=1
            )


class TestValidation:
    def test_unknown_mode_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_word_seed_experiment(session_factory=session_factory, mode="telepathy")

    def test_zero_populations_rejected(self, session_factory):
        with pytest.raises(ValueError, match="populations must be"):
            run_word_seed_experiment(session_factory=session_factory, populations=0)

    def test_experiment_row_completed(self, session_factory):
        from app.persistence.models import ExperimentModel

        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=["light"], populations=1
        )
        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, report["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "word_seed"
            assert experiment.model_configuration["seeds"] == ["light"]

    def test_export_writes_valid_json(self, session_factory, tmp_path):
        report = run_word_seed_experiment(
            session_factory=session_factory, mode="scripted", seeds=["light"], populations=1
        )
        path = tmp_path / "wordseed.json"
        from app.experiments.wordseed import export_report

        export_report(report, str(path))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["comparison"] == report["comparison"]
