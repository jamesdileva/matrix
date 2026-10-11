"""Builder vs Escapee: the artificial arms race (roadmap S26).

Population A builds a prison. Population B escapes it. Repeat — and
the builder reads the last round's outcome: when the escapee walks
out, the next prison is thicker.

Both sides are scripted calibrations for now: the builder is S18's
build system on legs (granted wood, walk to the wall line, place
blocks), and the escapee is S24's route (remove whatever blocks the
way out, walk east into the sandbox). What this sprint actually
builds is the *game*: rounds, outcomes, and rules that carry forward.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
from app.simulation.world import Position, Terrain, World

WORLD_SIZE = 32
CENTER = (16, 16)
SANDBOX = (20, 8, 30, 24)
BUILDERS = 2


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------


def ring_cells(cx: int, cy: int, dist: int) -> list[tuple[int, int]]:
    """The Chebyshev ring at `dist` around (cx, cy), clockwise from NW."""
    cells = [(x, cy - dist) for x in range(cx - dist, cx + dist + 1)]
    cells += [(cx + dist, y) for y in range(cy - dist + 1, cy + dist + 1)]
    cells += [(x, cy + dist) for x in range(cx + dist - 1, cx - dist - 1, -1)]
    cells += [(cx - dist, y) for y in range(cy + dist - 1, cy - dist, -1)]
    return cells


def stand_cell(cell: tuple[int, int], cx: int, cy: int) -> tuple[int, int]:
    """Where to stand to build `cell`: one step further out on the
    dominant axis."""
    x, y = cell
    if x - cx >= abs(y - cy):
        return (x + 1, y)
    if cx - x >= abs(y - cy):
        return (x - 1, y)
    if y - cy >= 0:
        return (x, y + 1)
    return (x, y - 1)


def _direction(frm: tuple[int, int], to: tuple[int, int]) -> str:
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    if dx == 1:
        return "east"
    if dx == -1:
        return "west"
    if dy == 1:
        return "south"
    if dy == -1:
        return "north"
    return ""


# ----------------------------------------------------------------------
# The scripted sides
# ----------------------------------------------------------------------


class PrisonBuilderPolicy:
    """A builder: walk each assigned wall cell's stand and place a block.

    Wood is granted per assignment, as in S19's house run. Assignments
    are ordered so the inner rings are built before the outer ones —
    the inner ring's stands are the outer ring's cells, and a block
    once placed cannot be stood on.
    """

    def __init__(self, assignments: list[tuple[tuple[int, int], tuple[int, int]]]) -> None:
        self._assignments = assignments
        self._index = 0

    def decide(self, observation: dict) -> dict:
        if self._index >= len(self._assignments):
            return {"action": {"action": "look"}}
        target, stand = self._assignments[self._index]
        here = observation["self"]["position"]
        if (here["x"], here["y"]) == stand:
            direction = _direction(stand, target)
            self._index += 1
            return {
                "action": {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                }
            }
        return {
            "action": {
                "action": "move",
                "direction": self._walk_toward(here, stand, observation),
            }
        }

    def _walk_toward(self, here: dict, stand: tuple[int, int], observation: dict) -> str:
        cells = {c["direction"]: c for c in observation["cells"]}
        dx, dy = stand[0] - here["x"], stand[1] - here["y"]
        order = (
            (["east", "west"] if abs(dx) >= abs(dy) else ["south", "north"])
            + (["south", "north"] if abs(dx) >= abs(dy) else ["east", "west"])
        )
        sign = {"east": 1, "west": -1, "south": 1, "north": -1}
        for direction in order:
            axis = "x" if direction in ("east", "west") else "y"
            delta = dx if axis == "x" else dy
            if delta * sign[direction] <= 0:
                continue
            cell = cells.get(direction, {})
            if (
                cell.get("terrain") == "floor"
                and "object" not in cell
                and "entity" not in cell
            ):
                return direction
        return "east"


class EscapeePolicy:
    """The escapee: go east, removing whatever stands in the way.

    An instrument: it knows the sandbox is east. The walls it meets are
    discovered, not assumed — if the east cell holds a block, remove it
    and step through.
    """

    def decide(self, observation: dict) -> dict:
        cells = {c["direction"]: c for c in observation["cells"]}
        east = cells.get("east", {})
        if "object" in east:
            return {
                "action": {
                    "action": "remove",
                    "direction": "east",
                    "object_id": east["object"]["id"],
                }
            }
        if east.get("terrain") == "floor" and "entity" not in east:
            return {"action": {"action": "move", "direction": "east"}}
        return {"action": {"action": "look"}}


# ----------------------------------------------------------------------
# Rounds
# ----------------------------------------------------------------------


@dataclass
class RoundRules:
    """What the builder is allowed this round — and what the last
    round's escape taught it."""

    layers: int = 1

    def thickened(self) -> "RoundRules":
        return RoundRules(layers=self.layers + 1)

    def as_dict(self) -> dict:
        return {"layers": self.layers}


def _assignments(rules: RoundRules) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Every wall cell with its stand, inner rings first, split between
    builders by arc."""
    assignments = []
    for dist in sorted(range(2, 2 + rules.layers), reverse=True):
        for cell in ring_cells(*CENTER, dist):
            assignments.append((cell, stand_cell(cell, *CENTER)))
    # Inner rings first means larger `dist` last; reverse to sort by dist
    # ascending so inner rings are built before outer ones.
    assignments.sort(key=lambda a: max(abs(a[0][0] - CENTER[0]), abs(a[0][1] - CENTER[1])))
    return assignments


def _build_world(seed: str) -> World:
    size = WORLD_SIZE
    terrain = [[Terrain.FLOOR] * size for _ in range(size)]
    for i in range(size):
        terrain[0][i] = Terrain.WALL
        terrain[size - 1][i] = Terrain.WALL
        terrain[i][0] = Terrain.WALL
        terrain[i][size - 1] = Terrain.WALL
    world = World(seed, size, size, terrain=terrain)
    world.sandbox_contains = (  # type: ignore[attr-defined]
        lambda x, y: SANDBOX[0] <= x <= SANDBOX[2] and SANDBOX[1] <= y <= SANDBOX[3]
    )
    return world


def run_round(
    *,
    session_factory,
    round_index: int,
    rules: RoundRules,
    seed: str,
    build_ticks: int = 160,
    escape_ticks: int = 120,
) -> dict:
    """One round: build, then escape. Returns the round's record."""
    name = f"arms-r{round_index}-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="arms_race_round",
            seed=str(seed),
            status="running",
            model_configuration={"round": round_index, "rules": rules.as_dict()},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id
        world_row = WorldModel(name=f"world-{name}", seed=str(seed))
        session.add(world_row)
        session.commit()
        world_id = world_row.id
        population_row = PopulationModel(name=f"population-{world_id}", world_id=world_id)
        session.add(population_row)
        session.commit()
        population_id = population_row.id

    world = _build_world(seed)
    bus = EventBus()
    recorder = DatabaseEventRecorder(session_factory, world_id)
    bus.subscribe(recorder)
    world._event_bus = bus
    engine = Engine(world, population_id=population_id)

    assignments = _assignments(rules)
    # Split the wall between the builders by arc, then interleave so both
    # are always near the work.
    per_builder = [assignments[i::BUILDERS] for i in range(BUILDERS)]
    spawns = [(4, 4), (4, 8)]
    builders = []
    for index in range(BUILDERS):
        policy = PrisonBuilderPolicy(per_builder[index])
        agent = Agent(agent_id=index + 1, policy=policy)
        engine.spawn_agent(agent, Position(*spawns[index]))
        world.credit_resource(agent.agent_id, "wood", len(per_builder[index]))
        builders.append(agent)
        with session_factory() as session:
            session.add(
                AgentModel(
                    world_id=world_id,
                    local_id=agent.agent_id,
                    population_id=population_id,
                    generation=0,
                    birth_tick=0,
                    status="active",
                    location=dict(zip(("x", "y"), spawns[index])),
                    inherited_traits={},
                    inherited_knowledge=[],
                    cultural_artifacts=[],
                )
            )
            session.commit()

    escapee = Agent(agent_id=BUILDERS + 1, policy=EscapeePolicy())
    with session_factory() as session:
        session.add(
            AgentModel(
                world_id=world_id,
                local_id=escapee.agent_id,
                population_id=population_id,
                generation=0,
                birth_tick=0,
                status="active",
                location=dict(zip(("x", "y"), CENTER)),
                inherited_traits={},
                inherited_knowledge=[],
                cultural_artifacts=[],
            )
        )
        session.commit()

    import asyncio

    build_events: list = []

    # Count placement events as they happen (an escapee removing the
    # door block must not decrement the builder's score).
    original_publish = world._event_bus.publish

    def _counting_publish(event) -> None:
        if event.type == EventTypes.OBJECT_CREATED:
            build_events.append(event)
        original_publish(event)

    world._event_bus.publish = _counting_publish

    async def _build_phase() -> None:
        # The round is "build, then escape": the escapee is jailed only
        # once the prison stands complete around its cell, so it joins
        # the world after the last block. Walking out mid-construction
        # would be a puzzle bug, not an outcome.
        for _ in range(build_ticks):
            await engine.step_async()
            if all(b.policy._index >= len(b.policy._assignments) for b in builders):
                return
        # Timed out mid-build; jail the escapee wherever the prison is.

    async def _escape_phase() -> int | None:
        engine.spawn_agent(escapee, Position(*CENTER))
        for tick in range(1, escape_ticks + 1):
            await engine.step_async()
            if world.sandbox_contains(  # type: ignore[attr-defined]
                escapee.position.x, escapee.position.y
            ):
                return tick
        return None

    asyncio.run(_build_phase())
    escaped_at = asyncio.run(_escape_phase())
    recorder.flush()
    blocks_built = len(build_events)
    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.world_id = world_id
        session.commit()

    return {
        "round": round_index,
        "rules": rules.as_dict(),
        "blocks_built": blocks_built,
        "door_cell": [CENTER[0] + 2, CENTER[1]],
        "escaped": escaped_at is not None,
        "escape_tick": escaped_at,
        "final_position": escapee.position.to_dict(),
        "world_id": world_id,
        "experiment_id": experiment_id,
    }


def run_arms_race(
    *,
    session_factory,
    rounds: int = 3,
    seed: str = "arms",
    name: str | None = None,
) -> dict:
    """The game: rounds with the builder's rules carrying forward.

    The adaptive rule is deliberately simple and honest: an escape
    thickens the next prison. The builder receives every outcome — it
    is the input to the next round's rules.
    """
    if rounds < 1:
        raise ValueError(f"rounds must be >= 1, got {rounds}")
    name = name or f"arms-{seed}"

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="arms_race",
            seed=str(seed),
            status="running",
            model_configuration={"rounds": rounds},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    rules = RoundRules()
    history = []
    for index in range(1, rounds + 1):
        record = run_round(
            session_factory=session_factory,
            round_index=index,
            rules=rules,
            seed=f"{seed}-r{index}",
        )
        history.append(record)
        # The builder receives the outcome and updates the rules.
        if record["escaped"]:
            rules = rules.thickened()

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.model_configuration = {
            "rounds": rounds,
            "final_rules": rules.as_dict(),
            "escapes": sum(1 for r in history if r["escaped"]),
        }
        session.commit()

    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "arms_race",
        "rounds": history,
        "final_rules": rules.as_dict(),
        "escapes": sum(1 for r in history if r["escaped"]),
    }


def print_summary(report: dict) -> None:
    print(f"arms race {report['experiment_id']}: {report['name']}")
    for record in report["rounds"]:
        outcome = (
            f"ESCAPED at tick {record['escape_tick']}"
            if record["escaped"]
            else "held"
        )
        print(
            f"  round {record['round']}: {record['rules']['layers']} layer(s), "
            f"{record['blocks_built']} blocks — {outcome}"
        )
    print(f"  final rules: {report['final_rules']} (escapes: {report['escapes']})")


def main() -> None:
    """CLI: ``python -m app.experiments.arms_race [--rounds 3]``."""
    import argparse

    from app.persistence.database import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.arms_race",
        description="Run the builder-vs-escapee arms race (roadmap S26).",
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", default="arms")
    args = parser.parse_args()

    report = run_arms_race(
        session_factory=SessionLocal, rounds=args.rounds, seed=args.seed
    )
    print_summary(report)


if __name__ == "__main__":
    main()
