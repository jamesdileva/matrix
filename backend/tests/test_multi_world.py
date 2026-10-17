"""S39 — the multi-world laboratory: templates, seeds, comparison.

The roadmap's verification — "run the same experiment in 10 worlds" — is
the study section; the template, determinism and analytics sections are
the build items it rests on.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.worlds import router as worlds_router
from app.experiments.multi_world import (
    MEASURES,
    TEMPLATES,
    WorldTemplate,
    cross_world_analytics,
    export_study,
    resolve_template,
    run_study,
    run_world,
)
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'lab.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tpl.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    application = FastAPI()
    application.include_router(worlds_router, prefix="/api")
    application.state.worlds = WorldRegistry(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    with TestClient(application) as test_client:
        yield test_client
    engine.dispose()


# ----------------------------------------------------------------------
# Templates
# ----------------------------------------------------------------------


class TestTemplates:
    def test_a_template_round_trips(self):
        template = WorldTemplate(
            "custom", 24, 24, 5, ("gather", "wander"), 70, "mine"
        )
        assert WorldTemplate.from_dict(template.to_dict()) == template

    def test_every_builtin_template_has_the_fields_a_world_needs(self):
        assert TEMPLATES  # the shelf is not empty
        for template in TEMPLATES.values():
            assert template.width >= 8 and template.height >= 8
            assert template.agents >= 1
            assert template.ticks >= 1
            assert set(template.policies) <= {"wander", "forage", "gather"}

    def test_unknown_template_is_refused(self):
        with pytest.raises(ValueError, match="unknown template"):
            resolve_template("nowhere")

    def test_world_kwargs_carry_the_rotation_as_a_spawn_rule(self):
        kwargs = resolve_template("village").world_kwargs(seed="s")
        assert kwargs["seed"] == "s"
        assert kwargs["agents"] == TEMPLATES["village"].agents
        assert kwargs["populations"][0]["policies"] == list(TEMPLATES["village"].policies)


# ----------------------------------------------------------------------
# One world
# ----------------------------------------------------------------------


class TestOneWorld:
    def test_a_world_runs_and_reports_every_measure(self):
        report = run_world(resolve_template("void"), "run", ticks=20)
        for measure in MEASURES:
            assert measure in report
        assert report["actions"] > 0
        assert report["moves"] > 0
        assert report["template"] == "void"

    def test_the_same_seed_reproduces_the_same_history(self):
        first = run_world(resolve_template("void"), "same", ticks=25)
        second = run_world(resolve_template("void"), "same", ticks=25)
        assert first == second

    def test_independent_seeds_diverge(self):
        reports = [run_world(resolve_template("void"), f"seed-{i}", ticks=30) for i in range(5)]
        # Different seeds lay different worlds, so at least one measure
        # differs between any two of them.
        fingerprints = {(r["moves"], r["objects_remaining"], r["stock"]) for r in reports}
        assert len(fingerprints) > 1


# ----------------------------------------------------------------------
# Cross-world analytics
# ----------------------------------------------------------------------


class TestCrossWorldAnalytics:
    def test_analytics_summarize_every_measure(self):
        runs = [run_world(resolve_template("void"), f"a-{i}", ticks=20) for i in range(4)]
        analytics = cross_world_analytics(runs)
        assert analytics["worlds"] == 4
        assert set(analytics["measures"]) == set(MEASURES)
        for summary in analytics["measures"].values():
            assert summary["n"] == 4
            assert summary["min"] <= summary["mean"] <= summary["max"]
        # totals add up the same measure across the worlds
        assert analytics["totals"]["moves"] == sum(r["moves"] for r in runs)

    def test_identical_worlds_differ_nowhere(self):
        # One seed, one template, run again and again: the same history.
        run = run_world(resolve_template("void"), "one", ticks=20)
        analytics = cross_world_analytics([run, dict(run), dict(run)])
        assert analytics["differing_measures"] == 0
        assert analytics["differing_fraction"] == 0.0


# ----------------------------------------------------------------------
# The study: the same experiment in many worlds
# ----------------------------------------------------------------------


class TestTheStudy:
    def test_the_same_experiment_in_ten_worlds(self, session_factory):
        """The roadmap's check: run the same experiment in 10 worlds."""
        study = run_study(session_factory=session_factory, worlds=10, template="void", seed="ten")

        assert len(study["runs"]) == 10
        assert study["comparison"]["worlds"] == 10
        assert [run["index"] for run in study["runs"]] == list(range(10))
        # every world is a distinct seed
        seeds = [run["seed"] for run in study["runs"]]
        assert len(set(seeds)) == 10
        # the comparison is a full summary, not raw tallies
        for summary in study["comparison"]["measures"].values():
            assert set(summary) == {"n", "mean", "stdev", "min", "max"}

    def test_the_study_is_deterministic(self, session_factory):
        first = run_study(session_factory=session_factory, worlds=4, template="void", seed="rep")
        second = run_study(session_factory=session_factory, worlds=4, template="void", seed="rep")
        assert first["comparison"] == second["comparison"]

    def test_varying_the_template_holds_the_seed(self, session_factory):
        study = run_study(
            session_factory=session_factory,
            worlds=3,
            vary="template",
            templates=["void", "village", "crowded"],
            seed="one-seed",
        )
        assert [run["template"] for run in study["runs"]] == ["void", "village", "crowded"]
        assert {run["seed"] for run in study["runs"]} == {"one-seed"}
        # different recipes produce different histories
        assert study["comparison"]["differing_measures"] > 0

    def test_the_study_is_recorded_and_exportable(self, session_factory, tmp_path):
        from sqlalchemy.orm import Session

        study = run_study(
            session_factory=session_factory,
            worlds=3,
            template="void",
            seed="rec",
            export_path=str(tmp_path / "study.json"),
        )
        # the experiment row is completed
        engine = session_factory.kw["bind"]
        with Session(engine) as session:
            row = session.get(ExperimentModel, study["experiment_id"])
            assert row.status == "completed"
            assert row.scenario == "multi_world"

        # the export is the whole study
        written = json.loads((tmp_path / "study.json").read_text(encoding="utf-8"))
        assert written["comparison"] == study["comparison"]
        assert len(written["runs"]) == 3


# ----------------------------------------------------------------------
# The running server exposes the shelf
# ----------------------------------------------------------------------


class TestTemplateAPI:
    def test_templates_are_listed(self, client):
        body = client.get("/api/templates").json()
        names = {template["name"] for template in body["templates"]}
        assert names == set(TEMPLATES)

    def test_a_world_can_be_founded_from_a_template(self, client):
        response = client.post(
            "/api/worlds",
            json={"seed": "from-template", "template": "crowded", "autostart": False},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["width"] == TEMPLATES["crowded"].width
        assert data["height"] == TEMPLATES["crowded"].height
        assert data["agent_count"] == TEMPLATES["crowded"].agents

    def test_an_unknown_template_is_a_400(self, client):
        response = client.post(
            "/api/worlds",
            json={"seed": "x", "template": "nowhere", "autostart": False},
        )
        assert response.status_code == 400
