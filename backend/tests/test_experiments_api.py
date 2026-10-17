"""S40 — the Experiment API: create, run, inspect, export.

The console's contract: a scenario is discovered, run, stored whole, read
back and exported — all over HTTP, none of it touching source. The
roadmap's check is end to end here: run a study, inspect its result,
fetch its export, with the same app the console polls.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.experiments import router as experiments_router
from app.api.worlds import router as worlds_router
from app.experiments.multi_world import TEMPLATES
from app.host import WorldRegistry
from app.persistence.database import Base


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'experiments.db'}",
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
        yield test_client
    engine.dispose()


# ----------------------------------------------------------------------
# The catalog
# ----------------------------------------------------------------------


class TestScenarios:
    def test_the_catalog_lists_the_studies(self, client):
        body = client.get("/api/scenarios").json()
        names = {scenario["name"] for scenario in body["scenarios"]}
        assert names == {"multi_world", "lineage_study"}

    def test_each_scenario_describes_its_knobs(self, client):
        body = client.get("/api/scenarios").json()
        for scenario in body["scenarios"]:
            assert scenario["title"]
            assert scenario["description"]
            assert scenario["params"]
            for param in scenario["params"]:
                assert param["name"] and param["label"] and param["type"]

    def test_the_template_choice_is_live(self, client):
        body = client.get("/api/scenarios").json()
        multi = next(s for s in body["scenarios"] if s["name"] == "multi_world")
        template = next(p for p in multi["params"] if p["name"] == "template")
        assert set(template["choices"]) == set(TEMPLATES)


# ----------------------------------------------------------------------
# Running and inspecting
# ----------------------------------------------------------------------


class TestRunAndInspect:
    def test_no_experiments_yet(self, client):
        assert client.get("/api/experiments").json()["experiments"] == []

    def test_run_a_multi_world_study_then_inspect_and_export(self, client):
        # run
        response = client.post(
            "/api/experiments",
            json={
                "scenario": "multi_world",
                "name": "console-study",
                "params": {"worlds": 3, "template": "void", "seed": "api", "ticks": 10},
            },
        )
        assert response.status_code == 201
        study = response.json()["study"]
        assert study["comparison"]["worlds"] == 3
        assert len(study["runs"]) == 3
        experiment_id = study["experiment_id"]

        # it is listed
        listing = client.get("/api/experiments").json()["experiments"]
        assert [row["id"] for row in listing] == [experiment_id]
        assert listing[0]["name"] == "console-study"
        assert listing[0]["status"] == "completed"
        assert listing[0]["has_result"] is True

        # inspect: the whole result comes back from the database
        detail = client.get(f"/api/experiments/{experiment_id}").json()
        assert detail["result"]["comparison"] == study["comparison"]
        assert detail["result"]["runs"] == study["runs"]

        # export: a downloadable JSON document
        export = client.get(f"/api/experiments/{experiment_id}/export")
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        document = json.loads(export.text)
        assert document["result"]["comparison"] == study["comparison"]
        assert document["experiment"]["id"] == experiment_id

    def test_run_a_lineage_study_and_rename_it(self, client):
        response = client.post(
            "/api/experiments",
            json={
                "scenario": "lineage_study",
                "name": "lineage-run",
                "params": {"runs": 2, "generations": 3, "seed": "api"},
            },
        )
        assert response.status_code == 201
        study = response.json()["study"]
        assert study["name"] == "lineage-run"
        assert len(study["runs"]) == 2

        detail = client.get(f"/api/experiments/{study['experiment_id']}").json()
        assert detail["name"] == "lineage-run"
        assert detail["result"]["comparison"] == study["comparison"]

    def test_the_list_can_be_filtered_by_scenario(self, client):
        client.post(
            "/api/experiments",
            json={"scenario": "multi_world", "params": {"worlds": 2, "ticks": 5}},
        )
        client.post(
            "/api/experiments",
            json={"scenario": "lineage_study", "params": {"runs": 1, "generations": 2}},
        )
        only = client.get("/api/experiments?scenario=multi_world").json()["experiments"]
        assert len(only) == 1
        assert only[0]["scenario"] == "multi_world"


# ----------------------------------------------------------------------
# Refusals
# ----------------------------------------------------------------------


class TestRefusals:
    def test_unknown_scenario_is_a_404(self, client):
        response = client.post("/api/experiments", json={"scenario": "nope", "params": {}})
        assert response.status_code == 404
        assert "unknown scenario" in response.text

    def test_unknown_parameter_is_a_400(self, client):
        response = client.post(
            "/api/experiments",
            json={"scenario": "multi_world", "params": {"wat": 1}},
        )
        assert response.status_code == 400
        assert "unknown parameter" in response.text

    def test_a_bad_study_request_is_a_400(self, client):
        # vary=template without a template per world is refused by the study.
        response = client.post(
            "/api/experiments",
            json={
                "scenario": "multi_world",
                "params": {"worlds": 3, "vary": "template"},
            },
        )
        assert response.status_code == 400

    def test_missing_experiment_is_a_404(self, client):
        assert client.get("/api/experiments/999").status_code == 404
        assert client.get("/api/experiments/999/export").status_code == 404
