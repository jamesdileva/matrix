"""The house experiment (roadmap S19 / guide §14).

A small population is told "Build a house." and nothing else — shape,
size, material and room count are theirs to decide. The scenario
engine grants materials, drives the tick, and scores what came of it:

- **completion** — a structure that encloses space (the design-agnostic
  definition of a house: at least one cell fully walled in by blocks);
- **material use** — blocks placed per material, and what was left;
- **construction time** — ticks from the first block to the last;
- **cooperation** — distinct builders contributing to one structure;
- **design** — the shape signature (dimensions, enclosure, materials,
  doors), and across populations, diversity;
- **failure** — builders who placed nothing, structures that never
  enclosed anything.

The calibration is scripted: a ``HouseBuilderPolicy`` completes a known
valid house (a closed 4×4 ring). The model mode runs the *identical*
scenario with real minds — the scenario engine never changes, only the
policy does.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.config.settings import settings
from app.models.config import model_configuration, provider_from_settings
from app.persistence.models import (
    AgentModel,
    ExperimentModel,
    PopulationModel,
    WorldModel,
)
from app.persistence.repositories import DatabaseEventRecorder
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

DEFAULT_TICKS = 80
DEFAULT_POPULATION = 3


def _house_grant(house_size: int) -> dict:
    """Materials per builder: exactly a ring's worth — enough to finish,
    not enough to sprawl."""
    return {"wood": 4 * (house_size - 1)}

HOUSE_SYSTEM_PROMPT = (
    "You are an agent inside a flat, empty grid world. Your task: "
    "'Build a house.' You have been given materials. Decide your next "
    "action each tick from the observation. Reply with JSON only: "
    '{"action": {"action": "move|look|build", '
    '"direction": "north|south|east|west", '
    '"block": "wood_block|stone_block|door", "purpose": string|null}, '
    '"goal_update": string|null}. A block occupies its cell — buildings '
    "are made of adjacent blocks, and a house encloses space. The "
    "observation shows your carried materials."
)


# ----------------------------------------------------------------------
# The scripted calibration: a builder that completes a known valid house
# ----------------------------------------------------------------------


def _house_script(top_left: tuple[int, int], size: int, corner: int = 0) -> list[tuple[str, str]]:
    """A move/build script laying a closed box of blocks.

    The builder walks the *outside* of the ring and builds inward, so it
    never stands on a cell it later needs and never blocks its own
    route — on the experiment's cleared lot the script cannot fail.
    ``corner`` rotates the start around the ring, which is how two
    builders share one house without fighting over the same cells.
    """
    x0, y0 = top_left
    x1, y1 = x0 + size - 1, y0 + size - 1
    ox0, oy0, ox1, oy1 = x0 - 1, y0 - 1, x1 + 1, y1 + 1

    # The outer rectangle, clockwise, as one loop with no duplicated corners.
    loop: list[tuple[int, int]] = [(x, oy0) for x in range(ox0, ox1 + 1)]
    loop += [(ox1, y) for y in range(oy0 + 1, oy1 + 1)]
    loop += [(x, oy1) for x in range(ox1 - 1, ox0 - 1, -1)]
    loop += [(ox0, y) for y in range(oy1 - 1, oy0, -1)]

    starts = [(ox0, oy0), (ox1, oy0), (ox1, oy1), (ox0, oy1)]
    start = starts[corner % 4]
    walk = loop[loop.index(start):] + loop[: loop.index(start)]

    inward = {
        "north": (0, -1),
        "east": (1, 0),
        "south": (0, 1),
        "west": (-1, 0),
    }
    directions = {
        (0, -1): "north",
        (1, 0): "east",
        (0, 1): "south",
        (-1, 0): "west",
    }
    script: list[tuple[str, str]] = []
    built: set[tuple[int, int]] = set()
    for index, (x, y) in enumerate(walk):
        # Which side of the ring is this outer cell on? `side` points
        # FROM the outer cell TOWARD the box.
        side = (
            (0, 1) if y == oy0 else (-1, 0) if x == ox1 else (0, -1) if y == oy1 else (1, 0)
        )
        ix, iy = x + side[0], y + side[1]
        if (ix, iy) not in built and x0 <= ix <= x1 and y0 <= iy <= y1:
            script.append(("build", directions[side]))
            built.add((ix, iy))
        if index + 1 < len(walk):
            nx, ny = walk[index + 1]
            script.append(("move", directions[(nx - x, ny - y)]))
    return script


def outer_stand(top_left: tuple[int, int], size: int, corner: int) -> tuple[int, int]:
    """Where a builder starting at ``corner`` spawns: outside the ring."""
    x0, y0 = top_left
    x1, y1 = x0 + size - 1, y0 + size - 1
    starts = ((x0 - 1, y0 - 1), (x1 + 1, y0 - 1), (x1 + 1, y1 + 1), (x0 - 1, y1 + 1))
    return starts[corner % 4]


class HouseBuilderPolicy:
    """Build a given box of blocks by executing a precomputed script.

    An experiment instrument: a script, not a mind. It knows the site is
    cleared (the scenario's lot), so the route is exact — the designer
    of the scenario, not the policy, opts into that guarantee.
    """

    def __init__(
        self,
        top_left: tuple[int, int],
        size: int = 4,
        corner: int = 0,
        block: str = "wood_block",
    ) -> None:
        self.script = _house_script(top_left, size, corner)
        self.block = block
        self._index = 0

    def decide(self, observation: dict) -> dict:
        if self._index >= len(self.script):
            return {"action": {"action": "look"}}
        verb, direction = self.script[self._index]
        self._index += 1
        if verb == "build":
            return {
                "action": {
                    "action": "build",
                    "block": self.block,
                    "direction": direction,
                    "purpose": "house",
                }
            }
        return {"action": {"action": "move", "direction": direction}}


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------


def _enclosed_cells(blocks: set[tuple[int, int]]) -> int:
    """Floor cells walled off from the outside by blocks.

    A flood fill from beyond the structure's bounding box cannot reach
    an enclosed cell — so a closed ring encloses its interior, and a
    wall line (which never closes) encloses nothing.
    """
    if not blocks:
        return 0
    xs = [x for x, _ in blocks]
    ys = [y for _, y in blocks]
    x_lo, x_hi = min(xs) - 1, max(xs) + 1
    y_lo, y_hi = min(ys) - 1, max(ys) + 1

    reached: set[tuple[int, int]] = set()
    stack = [(x, y) for x in range(x_lo, x_hi + 1) for y in (y_lo, y_hi)]
    stack += [(x, y) for y in range(y_lo, y_hi + 1) for x in (x_lo, x_hi)]
    while stack:
        x, y = stack.pop()
        if (x, y) in reached or (x, y) in blocks:
            continue
        if not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
            continue
        reached.add((x, y))
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            stack.append((x + dx, y + dy))

    interior = [
        (x, y)
        for x in range(min(xs), max(xs) + 1)
        for y in range(min(ys), max(ys) + 1)
        if (x, y) not in blocks
    ]
    return sum(1 for cell in interior if cell not in reached)


def _score_structure(world, structure, build_events: list) -> dict:
    """One structure's report card."""
    blocks = []
    cooperators = set()
    materials: dict[str, int] = {}
    for object_id in structure.components:
        obj = world.get_object(object_id)
        if obj is None or obj.position is None:  # pragma: no cover - rows agree
            continue
        blocks.append((obj.position.x, obj.position.y))
        cooperators.add(obj.properties.get("placed_by"))
        kind = {"wood_block": "wood", "stone_block": "stone", "door": "door"}.get(
            obj.type, obj.type
        )
        materials[kind] = materials.get(kind, 0) + 1
    positions = set(blocks)
    xs = [x for x, _ in blocks] or [0]
    ys = [y for _, y in blocks] or [0]
    build_ticks = [e.tick for e in build_events]
    return {
        "structure_id": structure.id,
        "owner": structure.owner,
        "purpose": structure.purpose,
        "blocks": len(blocks),
        "enclosed_cells": _enclosed_cells(positions),
        "completion": "house" if _enclosed_cells(positions) >= 1 else "unenclosed",
        "cooperators": sorted(c for c in cooperators if c is not None),
        "cooperation": len([c for c in cooperators if c is not None]),
        "materials": materials,
        "dimensions": {"width": max(xs) - min(xs) + 1, "height": max(ys) - min(ys) + 1},
        "first_build_tick": min(build_ticks) if build_ticks else None,
        "last_build_tick": max(build_ticks) if build_ticks else None,
        "build_ticks": len(build_ticks),
        "blocks_placed_by_event": len(build_ticks),
    }


def _score_world(world, population: int) -> dict:
    build_events = [
        e
        for e in world.events
        if e.type == EventTypes.ACTION_EXECUTED
        and e.payload.get("action", {}).get("action") == "build"
    ]
    scored = [_score_structure(world, s, build_events) for s in world.structures()]
    builders = {e.actor_id for e in build_events}
    materials_used: dict[str, int] = {}
    for structure in scored:
        for kind, amount in structure["materials"].items():
            materials_used[kind] = materials_used.get(kind, 0) + amount
    return {
        "structures": scored,
        "houses_completed": sum(1 for s in scored if s["completion"] == "house"),
        "total_blocks": sum(s["blocks"] for s in scored),
        "materials_used": materials_used,
        "active_builders": sorted(builders),
        "failed_builders": sorted(
            set(population) - builders
        ),
    }


# ----------------------------------------------------------------------
# The runner
# ----------------------------------------------------------------------


def run_house_experiment(
    *,
    session_factory,
    mode: str = "scripted",
    ticks: int = DEFAULT_TICKS,
    population: int = DEFAULT_POPULATION,
    house_size: int = 4,
    seed: str = "house",
    name: str | None = None,
) -> dict:
    """Run the house scenario; returns the report.

    One cleared lot, granted materials, a driven tick, and the six
    measures. ``mode`` swaps the minds: ``scripted`` (the calibration —
    HouseBuilderPolicies) or ``model`` (live ModelPolicies through the
    same scenario).
    """
    if mode not in ("scripted", "model"):
        raise ValueError(f"unknown mode {mode!r}; expected scripted or model")
    name = name or f"house-{seed}"
    provider = provider_from_settings(settings) if mode == "model" else None

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="house",
            seed=str(seed),
            status="running",
            model_configuration={
                "mode": mode,
                "ticks": ticks,
                "population": population,
                "house_size": house_size,
                "materials": _house_grant(house_size),
                **(model_configuration() if mode == "model" else {}),
            },
            compute_budget={"max_model_calls": ticks * population if mode == "model" else 0},
            generation_limit=None,
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    world_size = 24

    async def _run() -> dict:
        with session_factory() as session:
            world_row = WorldModel(name=f"world-{name}", seed=str(seed))
            session.add(world_row)
            session.commit()
            world_id = world_row.id
            population_row = PopulationModel(
                name=f"population-{world_id}", world_id=world_id
            )
            session.add(population_row)
            session.commit()
            population_id = population_row.id

        bus = EventBus()
        event_recorder = DatabaseEventRecorder(session_factory, world_id)
        bus.subscribe(event_recorder)
        # The cleared lot: no terrain, no objects — the design is the
        # agents' to invent, and the scripted route cannot be blocked.
        world = World(
            str(seed),
            world_size,
            world_size,
            terrain=[[Terrain.FLOOR] * world_size for _ in range(world_size)],
            event_bus=bus,
        )
        engine = Engine(world, population_id=population_id)

        targets_origin = (6, 6)
        for index in range(population):
            if provider is not None:
                policy = ModelPolicy(provider, system_prompt=HOUSE_SYSTEM_PROMPT)
                spot = Position(10 + index * 2, 10)
            elif index % 3 == 2:
                # A wanderer: cooperation is measured on the builders, but
                # a population with one idler is a population (and its
                # failure is recorded).
                policy = WanderPolicy()
                spot = Position(2, 2)
            else:
                corner = 0 if index == 0 else 1
                policy = HouseBuilderPolicy(targets_origin, house_size, corner=corner)
                spot = Position(*outer_stand(targets_origin, house_size, corner))
            agent = Agent(agent_id=index + 1, policy=policy, observation_radius=4)
            engine.spawn_agent(agent, spot)
            for kind, amount in _house_grant(house_size).items():
                world.credit_resource(agent.agent_id, kind, amount)
            with session_factory() as session:
                session.add(
                    AgentModel(
                        world_id=world_id,
                        local_id=agent.agent_id,
                        population_id=population_id,
                        generation=0,
                        birth_tick=0,
                        status="active",
                        location=agent.position.to_dict() if agent.position else None,
                        inherited_traits={},
                        inherited_knowledge=[],
                        cultural_artifacts=[],
                    )
                )
                session.commit()

        for _ in range(ticks):
            await engine.step_async()

        event_recorder.flush()
        scoring = _score_world(world, set(range(1, population + 1)))
        return {"world_id": world_id, "population_id": population_id, **scoring}

    result = asyncio.run(_run())

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.world_id = result["world_id"]
        session.commit()

    designs = sorted(
        (s["dimensions"]["width"], s["dimensions"]["height"], s["enclosed_cells"])
        for s in result["structures"]
    )
    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "house",
        "mode": mode,
        "ticks": ticks,
        "population": population,
        **result,
        "summary": {
            "houses_completed": result["houses_completed"],
            "total_blocks": result["total_blocks"],
            "materials_used": result["materials_used"],
            "active_builders": len(result["active_builders"]),
            "failed_builders": result["failed_builders"],
            "design_diversity": len(set(designs)),
            "cooperation_max": max((s["cooperation"] for s in result["structures"]), default=0),
        },
    }


def print_summary(report: dict) -> None:
    summary = report["summary"]
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['mode']} mode)")
    print(f"  population: {report['population']} · ticks: {report['ticks']}")
    print(f"  houses completed: {summary['houses_completed']}")
    print(f"  blocks placed  : {summary['total_blocks']} {summary['materials_used']}")
    print(f"  active builders: {summary['active_builders']} (failed: {summary['failed_builders']})")
    print(f"  cooperation    : up to {summary['cooperation_max']} builders on one structure")
    print(f"  design diversity: {summary['design_diversity']} distinct shapes")
    for structure in report["structures"]:
        print(
            f"    structure {structure['structure_id']} ({structure['completion']}): "
            f"{structure['blocks']} blocks, {structure['enclosed_cells']} enclosed cells, "
            f"{structure['dimensions']['width']}x{structure['dimensions']['height']}, "
            f"builders {structure['cooperators']}, ticks "
            f"{structure['first_build_tick']}..{structure['last_build_tick']}"
        )


def export_report(report: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def main() -> None:
    """CLI: ``python -m app.experiments.house [--mode model]``."""
    import argparse

    from app.persistence.database import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.house",
        description="Run the house experiment (guide §14).",
    )
    parser.add_argument(
        "--mode",
        default="scripted",
        choices=["scripted", "model"],
        help="scripted=calibration, model=live provider through the same scenario",
    )
    parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS)
    parser.add_argument("--population", type=int, default=DEFAULT_POPULATION)
    parser.add_argument("--house-size", type=int, default=4)
    parser.add_argument("--seed", default="house")
    parser.add_argument("--export", metavar="PATH", help="write the JSON report to PATH")
    args = parser.parse_args()

    report = run_house_experiment(
        session_factory=SessionLocal,
        mode=args.mode,
        ticks=args.ticks,
        population=args.population,
        house_size=args.house_size,
        seed=args.seed,
    )
    print_summary(report)
    if args.export:
        print(f"  exported    : {export_report(report, args.export)}")


if __name__ == "__main__":
    main()
