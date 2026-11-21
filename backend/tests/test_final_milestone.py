"""S51 — the Final Milestone: the whole platform, one experiment, one verdict.

The attestation is the test subject: eight chapters must run their real
builders, every item of the Ultimate Definition of Done must reach
`demonstrated` honestly, a chapter failing its own check must mark its
item `failed` (the mirror, not the brochure), and the whole thing must
persist, export, and run through the API like any other study.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.experiments import router as experiments_router
from app.api.worlds import router as worlds_router
from app.experiments.final_milestone import (
    DEFINITION_OF_DONE,
    attestation,
    render_markdown,
    run_milestone,
)
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'milestone.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    application = FastAPI()
    application.include_router(worlds_router, prefix="/api")
    application.include_router(experiments_router, prefix="/api")
    application.state.session_factory = factory
    application.state.worlds = WorldRegistry(factory)
    with TestClient(application) as test_client:
        yield test_client, factory
    engine.dispose()


def test_the_milestone_demonstrates_every_item(session_factory, tmp_path):
    export_path = tmp_path / "milestone.json"
    study = run_milestone(
        session_factory=session_factory,
        seed="the-flood",
        export_path=str(export_path),
    )

    assert study["scenario"] == "the_flood"
    assert set(study["chapters"]) == {
        "lineage", "culture", "construction", "escape",
        "civilization", "games", "participation", "research",
    }
    assert study["demonstrated"] == len(DEFINITION_OF_DONE)
    assert all(v["status"] == "demonstrated" for v in study["attestation"])

    # each item cites what proves it beyond one bounded run
    for verdict in study["attestation"]:
        assert verdict["citation"]

    row = _row(session_factory, study["experiment_id"])
    assert row.status == "completed"
    assert row.result["closing"].startswith("8 of 8")

    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["attestation"] == study["attestation"]


def _row(factory, experiment_id: int) -> ExperimentModel:
    with factory() as session:
        return session.get(ExperimentModel, experiment_id)


def test_a_failing_chapter_marks_its_item_failed(session_factory, monkeypatch):
    """The attestation is a mirror, not a brochure: a chapter that fails
    its own check marks its item `failed`, and nothing else inflates."""
    from app.experiments import escape

    def refused(*, session_factory, **kwargs):
        return {
            "experiment_id": 0,
            "escaped": False,
            "escaped_at_tick": None,
            "actions_attempted": 3,
        }

    monkeypatch.setattr(escape, "run_escape_experiment", refused)

    study = run_milestone(session_factory=session_factory, seed="honest")

    verdicts = {v["item"]: v for v in study["attestation"]}
    assert verdicts["Escape"]["status"] == "failed"
    assert verdicts["Escape"]["evidence"]["escaped"] is False
    # every other item is untouched
    others = [v for item, v in verdicts.items() if item != "Escape"]
    assert all(v["status"] == "demonstrated" for v in others)
    assert study["demonstrated"] == len(DEFINITION_OF_DONE) - 1


def test_the_markdown_report_is_readable(session_factory):
    study = run_milestone(session_factory=session_factory, seed="readable")
    report = render_markdown(study)

    assert "# The Flood — Final Milestone Report" in report
    assert "## Ultimate Definition of Done" in report
    for verdict in study["attestation"]:
        assert f"**{verdict['status']}**" in report
        assert verdict["item"] in report
    assert "The operator can" in report
    assert "POST /api/worlds/{id}/participant/join" in report
    assert "sandbox for asking questions" in report


def test_the_milestone_runs_through_the_api(client):
    test_client, factory = client
    submitted = test_client.post(
        "/api/experiments",
        json={"scenario": "the_flood", "params": {"seed": "api-run"}},
    )
    assert submitted.status_code == 202

    from app.worker import run_worker

    run_worker(factory, once=True)

    listing = test_client.get("/api/experiments", params={"scenario": "the_flood"}).json()
    assert listing["experiments"][0]["status"] == "completed"

    experiment_id = listing["experiments"][0]["id"]
    detail = test_client.get(f"/api/experiments/{experiment_id}").json()
    assert detail["result"]["demonstrated"] == len(DEFINITION_OF_DONE)

    export = test_client.get(f"/api/experiments/{experiment_id}/export")
    assert export.status_code == 200
    assert json.loads(export.text)["result"]["scenario"] == "the_flood"


def test_the_catalog_lists_the_flood(client):
    test_client, _ = client
    names = {
        scenario["name"]
        for scenario in test_client.get("/api/scenarios").json()["scenarios"]
    }
    assert "the_flood" in names
