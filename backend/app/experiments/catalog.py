"""The experiment catalog: the studies the platform can run.

One entry per study — a title, its knobs, and a runner — shared by two
consumers: the API (which draws forms and enqueues runs) and the worker
(which executes them). Neither side owns this module; a runner is a thin
adapter over a study module's ``run_study``.

A runner's full signature is ``run(session_factory, params, name,
experiment_id=None)``. ``experiment_id`` comes from the enqueue path: the
API creates the row when a client submits a job, and the runner fills
*that* row instead of making its own. Studies called without an id (the
inline path, the CLIs) create their own row exactly as they always have.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


def template_choices() -> list[str]:
    from app.experiments.multi_world import TEMPLATES

    return sorted(TEMPLATES)


def optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def optional_list(value) -> list | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [item for item in str(value).split(",") if item]


def with_live_choices(param: dict) -> dict:
    if param["name"] in ("template", "templates") and param["type"] == "choice":
        param = {**param, "choices": template_choices()}
    return param


# --- the runners (thin adapters over the study modules) ---------------


def run_multi_world(
    session_factory,
    params: dict,
    name: str | None,
    experiment_id: int | None = None,
    profile: str | None = None,
) -> dict:
    from app.experiments.multi_world import run_study

    return run_study(
        session_factory=session_factory,
        worlds=int(params.get("worlds", 10)),
        template=str(params.get("template", "void")),
        seed=str(params.get("seed", "lab")),
        ticks=optional_int(params.get("ticks")),
        vary=str(params.get("vary", "seed")),
        templates=optional_list(params.get("templates")),
        name=name,
        experiment_id=experiment_id,
        max_actions=optional_int(params.get("max_actions")),
        profile=profile,
    )


def _rename_experiment(session_factory, experiment_id: int, name: str | None) -> None:
    """Post-hoc rename for studies that name themselves (lineage_study)."""
    if not name:
        return
    from app.persistence.models import ExperimentModel

    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        if row is not None:
            row.name = name
            session.commit()


def run_lineage_study(
    session_factory,
    params: dict,
    name: str | None,
    experiment_id: int | None = None,
    profile: str | None = None,
) -> dict:
    # S49: the profile is accepted for a uniform worker surface but not
    # yet applied — lineage runs pace themselves per generation.
    from app.experiments.lineage_study import run_study

    study = run_study(
        session_factory=session_factory,
        runs=int(params.get("runs", 3)),
        mode=str(params.get("mode", "full")),
        generations=int(params.get("generations", 12)),
        seed=str(params.get("seed", "study")),
        vary=str(params.get("vary", "seed")),
        models=optional_list(params.get("models")),
        experiment_id=experiment_id,
    )
    if name and study.get("experiment_id"):
        _rename_experiment(session_factory, study["experiment_id"], name)
        study["name"] = name
    return study


def run_observer_study(
    session_factory,
    params: dict,
    name: str | None,
    experiment_id: int | None = None,
    profile: str | None = None,
) -> dict:
    from app.experiments.observer import ParticipantPlan, run_study

    plan_data = params.get("participant_plan")
    plan = ParticipantPlan.from_dict(plan_data) if isinstance(plan_data, dict) else None
    return run_study(
        session_factory=session_factory,
        template=str(params.get("template", "void")),
        seed=str(params.get("seed", "observer")),
        ticks=optional_int(params.get("ticks")),
        participant_plan=plan,
        name=name,
        experiment_id=experiment_id,
        max_actions=optional_int(params.get("max_actions")),
        profile=profile,
    )


SCENARIOS: dict[str, Scenario] = {
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
            Param("max_actions", "max_actions", "int", None, minimum=1, maximum=1000000,
                  help="per-world action ceiling; leave blank for unlimited"),
        ),
        runner=run_multi_world,
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
        runner=run_lineage_study,
    ),
    "observer_vs_participant": Scenario(
        name="observer_vs_participant",
        title="Observer vs participant",
        description=(
            "Run two worlds from one seed — one left alone, one joined by a "
            "participant who joins a population, teaches an agent, assigns a "
            "task, places objects and speaks — then compare development, "
            "culture, behaviour, technology and communication, measure by "
            "measure. Same seed, same template, one difference."
        ),
        params=(
            Param("template", "template", "choice", "void", choices=["void"]),
            Param("seed", "seed", "str", "observer"),
            Param("ticks", "ticks", "int", None, minimum=1, maximum=10000,
                  help="leave blank for the template's own span"),
            Param("max_actions", "max_actions", "int", None, minimum=1, maximum=1000000,
                  help="per-world action ceiling; leave blank for unlimited"),
        ),
        runner=run_observer_study,
    ),
}


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(name)
    return SCENARIOS[name]


def scenarios_payload() -> list[dict]:
    """The catalog as data, with live choice lists (templates) resolved."""
    payload = []
    for scenario in SCENARIOS.values():
        entry = scenario.to_dict()
        entry["params"] = [with_live_choices(param) for param in entry["params"]]
        payload.append(entry)
    return payload
