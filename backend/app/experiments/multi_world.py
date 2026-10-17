"""S39 — the multi-world laboratory: many universes, one experiment.

One world is a history; many worlds from the same recipe, differing only
by seed, are a laboratory. This module gives the roadmap's four build
items a home:

- **world templates** — a ``WorldTemplate`` names a recipe (size, minds,
  span) that can be stamped out as many worlds as a study needs.
- **independent seeds** — each world gets its own seed, so its terrain
  and its objects are its own; with scripted minds the whole run is
  deterministic, which makes a repeated study reproduce exactly and a
  seed change a controlled difference.
- **experiment comparison** — ``run_study`` runs the same template in N
  worlds (or N templates under one seed) and compares them.
- **cross-world analytics** — ``cross_world_analytics`` summarizes every
  measure across the worlds: n, mean, spread, range — never a single
  raw tally, so two studies are comparable.

The study runs in memory and is exported whole as one JSON file, so a
laboratory result can leave the simulation and live in a paper. The
running server exposes the templates at ``GET /api/templates`` and can
found a world from one (``POST /api/worlds`` with ``template``).
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import ForagerPolicy, GathererPolicy, WanderPolicy
from app.simulation.world import Position, World

STUDY_SCENARIO = "multi_world"
RUN_SCENARIO = "multi_world_run"

# The cross-world measures, in words: the shape of a history that can be
# counted the same way in every universe.
MEASURES = (
    "actions",
    "moves",
    "gathers",
    "rejections",
    "births",
    "stock",
    "objects_remaining",
    "structures",
    "settlements",
)


@dataclass(frozen=True)
class WorldTemplate:
    """A recipe for a world: the constant a study varies around.

    ``policies`` names the minds in rotation (``wander``, ``forage``,
    ``gather``); a world is stamped out with ``agents`` of them, spread
    across free floor. ``ticks`` is how long the scenario runs. The
    recipe says nothing about the seed — that is always the study's.
    """

    name: str
    width: int = 16
    height: int = 16
    agents: int = 3
    policies: tuple[str, ...] = ("forage", "gather", "wander")
    ticks: int = 40
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorldTemplate":
        return cls(
            name=data["name"],
            width=data.get("width", 16),
            height=data.get("height", 16),
            agents=data.get("agents", 3),
            policies=tuple(data.get("policies", ("wander",))),
            ticks=data.get("ticks", 40),
            description=data.get("description", ""),
        )

    def world_kwargs(self, *, seed: str, tps: float = 6.0) -> dict:
        """The registry's ``create`` arguments that found this world.

        Every member of the template's rotation becomes a spawn rule, so
        a template instantiated on the live server is the same world the
        offline study runs.
        """
        policies = list(self.policies) or ["wander"]
        return {
            "seed": seed,
            "width": self.width,
            "height": self.height,
            "agents": self.agents,
            "tps": tps,
            "populations": [
                {"name": f"{self.name}", "members": self.agents, "policies": policies}
            ],
        }


# The built-in laboratory shelf. A study can pass its own instead.
TEMPLATES: dict[str, WorldTemplate] = {
    "void": WorldTemplate(
        "void", 16, 16, 3, ("forage", "gather", "wander"), 40,
        "the default lot: three minds, a short forage",
    ),
    "village": WorldTemplate(
        "village", 20, 20, 6, ("forage", "gather", "gather", "wander"), 60,
        "more hands, more mouths, on a roomier map",
    ),
    "sparse": WorldTemplate(
        "sparse", 32, 32, 2, ("gather", "wander"), 80,
        "a big quiet world with one thing to find",
    ),
    "crowded": WorldTemplate(
        "crowded", 12, 12, 8, ("forage", "wander"), 40,
        "eight minds on a postage stamp",
    ),
}


def resolve_template(name: str) -> WorldTemplate:
    if name not in TEMPLATES:
        raise ValueError(
            f"unknown template {name!r}; expected one of {sorted(TEMPLATES)}"
        )
    return TEMPLATES[name]


# ----------------------------------------------------------------------
# One world
# ----------------------------------------------------------------------


def _policy(name: str):
    if name == "wander":
        return WanderPolicy()
    if name == "forage":
        return ForagerPolicy()
    if name == "gather":
        return GathererPolicy("wood")
    raise ValueError(f"unknown policy {name!r}; expected wander, forage or gather")


def _spawn_spots(world: World, count: int) -> list[Position]:
    """``count`` free floor cells, spread across the map, deterministically."""
    free = [
        Position(x, y)
        for y in range(world.height)
        for x in range(world.width)
        if world.is_floor(Position(x, y)) and world.object_at(Position(x, y)) is None
    ]
    if not free or count <= 0:
        return []
    count = min(count, len(free))
    step = max(1, len(free) // count)
    return [free[min(index * step, len(free) - 1)] for index in range(count)]


def run_world(
    template: WorldTemplate,
    seed: str,
    *,
    ticks: int | None = None,
) -> dict:
    """Run the template in one world and report what happened there."""
    world = World.generate(str(seed), template.width, template.height)
    engine = Engine(world, population_id=1)
    policies = [_policy(name) for name in (template.policies or ("wander",))]
    for index, spot in enumerate(_spawn_spots(world, template.agents)):
        engine.spawn_agent(
            Agent(
                agent_id=index + 1,
                policy=policies[index % len(policies)],
                observation_radius=3,
            ),
            spot,
        )

    span = template.ticks if ticks is None else ticks
    for _ in range(span):
        engine.step()

    return {"template": template.name, "seed": str(seed), "ticks": span, **_events(world)}


def _events(world: World) -> dict:
    """The measures, read off the world and its timeline."""
    verbs: dict[str, int] = {}
    rejections = 0
    births = 0
    for event in world.events:
        if event.type == EventTypes.AGENT_BORN:
            births += 1
        elif event.type == EventTypes.ACTION_REJECTED:
            rejections += 1
        elif event.type == EventTypes.ACTION_EXECUTED:
            action = event.payload.get("action") or {}
            verb = action.get("action") if isinstance(action, dict) else None
            if verb:
                verbs[verb] = verbs.get(verb, 0) + 1

    stock: dict[str, int] = {}
    for entity_id in world.entity_ids:
        for kind, amount in world.resources(entity_id).items():
            stock[kind] = stock.get(kind, 0) + amount

    return {
        "actions": sum(verbs.values()),
        "moves": verbs.get("move", 0),
        "gathers": verbs.get("gather", 0),
        "rejections": rejections,
        "births": births,
        "stock": sum(stock.values()),
        "objects_remaining": len(world.objects),
        "structures": len(world.structures()),
        "settlements": len(world.settlements),
    }


# ----------------------------------------------------------------------
# Many worlds
# ----------------------------------------------------------------------


def _summary(values: list[float]) -> dict:
    """Comparable statistics for one measure across the worlds."""
    if not values:
        return {"n": 0, "mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": round(stats.fmean(values), 4),
        "stdev": round(stats.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def cross_world_analytics(runs: list[dict]) -> dict:
    """Every measure summarized across the worlds, plus running totals."""
    measures = {
        measure: _summary([float(run.get(measure, 0)) for run in runs])
        for measure in MEASURES
    }
    totals = {
        measure: sum(int(run.get(measure, 0)) for run in runs) for measure in MEASURES
    }
    # How much the worlds differ at all: the fraction of measures whose
    # spread is non-zero (a fully deterministic, identical-seed study is 0).
    differing = sum(1 for summary in measures.values() if summary["stdev"] > 0)
    return {
        "worlds": len(runs),
        "measures": measures,
        "totals": totals,
        "differing_measures": differing,
        "differing_fraction": round(differing / len(MEASURES), 4) if MEASURES else 0.0,
    }


def run_study(
    *,
    session_factory,
    worlds: int = 10,
    template: str = "void",
    seed: str = "lab",
    ticks: int | None = None,
    vary: str = "seed",
    templates: list[str] | None = None,
    export_path: str | None = None,
    name: str | None = None,
) -> dict:
    """Run the same experiment in ``worlds`` worlds and compare them.

    ``vary="seed"`` holds the template fixed and gives every world its own
    seed (the roadmap's experiment: the same scenario across independent
    universes). ``vary="template"`` holds the seed fixed and walks the
    world's recipe instead — ``templates`` names one per world.
    """
    if worlds < 1:
        raise ValueError(f"a study needs at least one world, got {worlds}")
    if vary not in ("seed", "template"):
        raise ValueError(f"unknown vary axis {vary!r}; expected seed or template")
    if vary == "template":
        if not templates:
            raise ValueError("varying the template needs one template name per world")
        if len(templates) != worlds:
            raise ValueError(
                f"varying the template needs one per world: {worlds} worlds, "
                f"{len(templates)} templates"
            )
        selected = [resolve_template(item) for item in templates]
    else:
        selected = [resolve_template(template)] * worlds

    label = name or f"lab-{seed}"
    config = {
        "vary": vary,
        "template": template,
        "templates": templates if vary == "template" else None,
        "worlds": worlds,
        "ticks": ticks,
        "measures": list(MEASURES),
    }
    with session_factory() as session:
        experiment = ExperimentModel(
            name=label,
            scenario=STUDY_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration=config,
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    run_records = []
    for index in range(worlds):
        chosen = selected[index]
        world_seed = str(seed) if vary == "template" else f"{seed}-{index}"
        report = run_world(chosen, world_seed, ticks=ticks)
        report["index"] = index
        report["experiment_id"] = experiment_id
        run_records.append(report)

    comparison = cross_world_analytics(run_records)
    study = {
        "experiment_id": experiment_id,
        "name": label,
        "scenario": STUDY_SCENARIO,
        "seed": seed,
        "vary": vary,
        "template": template,
        "templates": templates if vary == "template" else None,
        "ticks": ticks,
        "runs": run_records,
        "comparison": comparison,
        "measures": list(MEASURES),
    }

    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {**config, "comparison": comparison}
        session.commit()

    if export_path:
        study["export_path"] = export_study(study, export_path)
    return study


def export_study(study: dict, path: str) -> str:
    """Write the whole laboratory run to one JSON file; returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(study, indent=2, sort_keys=False), encoding="utf-8")
    return str(target)


def print_summary(study: dict) -> None:
    comparison = study["comparison"]
    axis = (
        "the template (" + ", ".join(t["template"] for t in study["runs"]) + ")"
        if study["vary"] == "template"
        else "the seed"
    )
    print(
        f"multi-world study {study['name']!r}: {comparison['worlds']} worlds, "
        f"varying {axis}"
    )
    for measure in MEASURES:
        summary = comparison["measures"][measure]
        print(
            f"  {measure:18s} mean {summary['mean']:>8}  stdev {summary['stdev']:>8}  "
            f"min {summary['min']:>8}  max {summary['max']:>8}"
        )
    print(
        f"  differing measures: {comparison['differing_measures']}/{len(MEASURES)} "
        f"({comparison['differing_fraction']})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.multi_world",
        description="Run the same experiment in many worlds and compare them (roadmap S39).",
    )
    parser.add_argument("--worlds", type=int, default=10)
    parser.add_argument("--template", default="void")
    parser.add_argument("--seed", default="lab")
    parser.add_argument("--ticks", type=int, default=None)
    parser.add_argument(
        "--vary", default="seed", choices=["seed", "template"],
        help="what differs between worlds: the seed, or the template",
    )
    parser.add_argument(
        "--templates", default=None,
        help="comma-separated template names, one per world, when --vary template",
    )
    parser.add_argument("--name", default=None)
    parser.add_argument("--export", default=None, help="write the study as JSON here")
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    templates = args.templates.split(",") if args.templates else None
    if args.vary == "template" and not templates:
        shelf = list(TEMPLATES)
        templates = [shelf[index % len(shelf)] for index in range(args.worlds)]

    study = run_study(
        session_factory=SessionLocal,
        worlds=args.worlds,
        template=args.template,
        seed=args.seed,
        ticks=args.ticks,
        vary=args.vary,
        templates=templates,
        export_path=args.export,
        name=args.name,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
