"""The Experiment API (S40, queue since S47): enqueue, inspect, export.

This is the console's other half. Every study the platform can run —
S32's lineage study, S39's multi-world laboratory, S46's observer pair —
is one entry in the scenario catalog (``app/experiments/catalog.py``,
shared with the worker), and every run is an ``ExperimentModel`` row
that keeps its whole result.

Since S47 the API does not run studies itself: ``POST /experiments``
validates the request and *enqueues* it (202) for the worker process
(``python -m app.worker``) — a long simulation can't block the console.
Clients that want the old synchronous behaviour pass ``"wait": true``
and get the study body inline (201), which is what the quick studies
and the tests use.

Routes:
- ``GET  /scenarios``            — the catalog (each study and its knobs).
- ``GET  /experiments``          — runs, newest first.
- ``GET  /experiments/{id}``     — one run, with its stored result.
- ``POST /experiments``          — enqueue (202) or run inline (``wait``: 201).
- ``GET  /experiments/{id}/export`` — the study as a downloadable JSON.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.experiments.catalog import SCENARIOS, Scenario, get_scenario, scenarios_payload
from app.persistence.models import ExperimentModel
from app.worker import enqueue as enqueue_experiment

router = APIRouter(tags=["experiments"])


class RunExperimentRequest(BaseModel):
    scenario: str
    name: str | None = None
    params: dict = Field(default_factory=dict)
    wait: bool = False


def _session_factory(request: Request):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        # Fall back to the running registry's storage so the API works
        # even in a host built without the explicit attribute.
        factory = getattr(request.app.state.worlds, "_session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="no session factory configured")
    return factory


def _scenario(name: str) -> Scenario:
    try:
        return get_scenario(name)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"unknown scenario {name!r}; expected one of {sorted(SCENARIOS)}",
        ) from None


def _name_override(session_factory, study: dict, name: str | None) -> dict:
    """A study names itself; a caller may still rename the row."""
    if not name:
        return study
    with session_factory() as session:
        row = session.get(ExperimentModel, study["experiment_id"])
        if row is not None:
            row.name = name
            session.commit()
    study["name"] = name
    return study


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


def _experiment_summary(row: ExperimentModel) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "scenario": row.scenario,
        "seed": row.seed,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "has_result": row.result is not None,
    }


@router.get("/scenarios")
def list_scenarios() -> dict:
    return {"scenarios": scenarios_payload()}


@router.get("/experiments")
def list_experiments(request: Request, scenario: str | None = None, limit: int = 50) -> dict:
    factory = _session_factory(request)
    limit = max(1, min(limit, 500))
    query = select(ExperimentModel)
    if scenario:
        query = query.where(ExperimentModel.scenario == scenario)
    query = query.order_by(ExperimentModel.id.desc()).limit(limit)
    with factory() as session:
        rows = session.scalars(query).all()
        return {"experiments": [_experiment_summary(row) for row in rows]}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int, request: Request) -> dict:
    factory = _session_factory(request)
    with factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no experiment {experiment_id}")
        return {
            **_experiment_summary(row),
            "configuration": row.model_configuration,
            "result": row.result,
        }


@router.post("/experiments")
def run_experiment(payload: RunExperimentRequest, request: Request, response: Response) -> dict:
    scenario = _scenario(payload.scenario)
    allowed = {param.name for param in scenario.params}
    unknown = sorted(set(payload.params) - allowed)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown parameter(s) for {scenario.name}: {unknown}; expected {sorted(allowed)}",
        )
    factory = _session_factory(request)

    if not payload.wait:
        # The default since S47: hand the study to the worker and answer
        # immediately — the API stays responsive during long simulations.
        experiment_id = enqueue_experiment(factory, scenario.name, payload.params, payload.name)
        with factory() as session:
            row = session.get(ExperimentModel, experiment_id)
        response.status_code = 202
        return {"queued": True, "experiment": _experiment_summary(row)}

    try:
        study = scenario.runner(factory, payload.params, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.status_code = 201
    return {"scenario": scenario.name, "study": study}


@router.get("/experiments/{experiment_id}/export")
def export_experiment(experiment_id: int, request: Request) -> Response:
    factory = _session_factory(request)
    with factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no experiment {experiment_id}")
        if row.result is None:
            raise HTTPException(
                status_code=409, detail=f"experiment {experiment_id} has no stored result"
            )
        document = {
            "experiment": _experiment_summary(row),
            "configuration": row.model_configuration,
            "result": row.result,
        }
    body = json.dumps(document, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="experiment-{experiment_id}.json"'
        },
    )
