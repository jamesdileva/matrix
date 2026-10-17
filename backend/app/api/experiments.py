"""The Experiment API (S40): create, run, inspect and export studies.

This is the console's other half. Every study the platform can run —
S32's lineage study, S39's multi-world laboratory — is one entry in a
scenario catalog, and every run is an `ExperimentModel` row that now
keeps its whole result, so inspect and export read the database rather
than re-running anything.

Routes:
- ``GET  /scenarios``            — the catalog (each study and its knobs).
- ``GET  /experiments``          — runs, newest first.
- ``GET  /experiments/{id}``     — one run, with its stored result.
- ``POST /experiments``          — run a scenario; returns the study.
- ``GET  /experiments/{id}/export`` — the study as a downloadable JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.persistence.models import ExperimentModel

router = APIRouter(tags=["experiments"])


# ----------------------------------------------------------------------
# The scenario catalog
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    """One knob a scenario exposes — enough for the console to draw a form."""

    name: str
    label: str
    type: str = "str"  # "int" | "str" | "bool" | "choice"
    default: object = None
    choices: list | None = None
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "help": self.help,
        }
        if self.choices is not None:
            data["choices"] = list(self.choices)
        if self.minimum is not None:
            data["min"] = self.minimum
        if self.maximum is not None:
            data["max"] = self.maximum
        return data


@dataclass(frozen=True)
class Scenario:
    """A runnable study: a title, its knobs, and how to run it."""

    name: str
    title: str
    description: str
    params: tuple[Param, ...] = ()
    runner: object = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "params": [param.to_dict() for param in self.params],
        }


def _template_choices() -> list[str]:
    from app.experiments.multi_world import TEMPLATES

    return sorted(TEMPLATES)


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_list(value) -> list | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [item for item in str(value).split(",") if item]


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


# --- the runners (thin adapters over the study modules) ---------------


def _run_multi_world(session_factory, params: dict, name: str | None) -> dict:
    from app.experiments.multi_world import run_study

    study = run_study(
        session_factory=session_factory,
        worlds=int(params.get("worlds", 10)),
        template=str(params.get("template", "void")),
        seed=str(params.get("seed", "lab")),
        ticks=_optional_int(params.get("ticks")),
        vary=str(params.get("vary", "seed")),
        templates=_optional_list(params.get("templates")),
        name=name,
    )
    return study


def _run_lineage_study(session_factory, params: dict, name: str | None) -> dict:
    from app.experiments.lineage_study import run_study

    study = run_study(
        session_factory=session_factory,
        runs=int(params.get("runs", 3)),
        mode=str(params.get("mode", "full")),
        generations=int(params.get("generations", 12)),
        seed=str(params.get("seed", "study")),
        vary=str(params.get("vary", "seed")),
        models=_optional_list(params.get("models")),
    )
    return _name_override(session_factory, study, name)


_SCENARIOS: dict[str, Scenario] = {
    "multi_world": Scenario(
        name="multi_world",
        title="Multi-world laboratory",
        description=(
            "Run the same template in N independent worlds (vary the seed) "
            "or walk the world's recipe under one seed (vary the template), "
            "and compare every measure across the worlds."
        ),
        params=(
            Param("worlds", "worlds", "int", 10, minimum=1, maximum=100),
            Param("template", "template", "choice", "void", choices=["void"]),
            Param("vary", "vary", "choice", "seed", choices=["seed", "template"]),
            Param("seed", "seed", "str", "lab"),
            Param("ticks", "ticks", "int", None, minimum=1, maximum=10000,
                  help="leave blank for the template's own span"),
            Param("templates", "templates", "str", None,
                  help="comma-separated templates, one per world, when vary=template"),
        ),
        runner=_run_multi_world,
    ),
    "lineage_study": Scenario(
        name="lineage_study",
        title="Lineage study",
        description=(
            "Run N lineages from the same founder's facts — varying the seed "
            "or the mind — and compare convergence, divergence, information "
            "loss, strategies and vocabulary."
        ),
        params=(
            Param("runs", "runs", "int", 3, minimum=1, maximum=50),
            Param(
                "mode", "mind", "choice", "full",
                choices=["full", "lossy", "altering", "negating", "new", "model"],
            ),
            Param("vary", "vary", "choice", "seed", choices=["seed", "model"]),
            Param("generations", "generations", "int", 12, minimum=1, maximum=100),
            Param("seed", "seed", "str", "study"),
            Param("models", "models", "str", None,
                  help="comma-separated minds, one per run, when vary=model"),
        ),
        runner=_run_lineage_study,
    ),
}


def _scenario(name: str) -> Scenario:
    if name not in _SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown scenario {name!r}; expected one of {sorted(_SCENARIOS)}",
        )
    return _SCENARIOS[name]


def scenarios_payload() -> list[dict]:
    """The catalog as data, with live choice lists (templates) resolved."""
    payload = []
    for scenario in _SCENARIOS.values():
        entry = scenario.to_dict()
        entry["params"] = [
            _with_live_choices(param) for param in entry["params"]
        ]
        payload.append(entry)
    return payload


def _with_live_choices(param: dict) -> dict:
    if param["name"] in ("template", "templates") and param["type"] == "choice":
        param = {**param, "choices": _template_choices()}
    return param


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


class RunExperimentRequest(BaseModel):
    scenario: str
    name: str | None = None
    params: dict = Field(default_factory=dict)


def _session_factory(request: Request):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        # Fall back to the running registry's storage so the API works
        # even in a host built without the explicit attribute.
        factory = getattr(request.app.state.worlds, "_session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="no session factory configured")
    return factory


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


@router.post("/experiments", status_code=201)
def run_experiment(payload: RunExperimentRequest, request: Request) -> dict:
    scenario = _scenario(payload.scenario)
    allowed = {param.name for param in scenario.params}
    unknown = sorted(set(payload.params) - allowed)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown parameter(s) for {scenario.name}: {unknown}; expected {sorted(allowed)}",
        )
    factory = _session_factory(request)
    try:
        study = scenario.runner(factory, payload.params, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
