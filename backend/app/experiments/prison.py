"""The prison sandbox: the first escape environment (roadmap S23).

A room with one door. The door is blocked by a stone the inhabitants
can carry away. Beyond it, the destination sandbox. The escape is
recorded as an ESCAPED event the moment an entity crosses into the
sandbox.

The verification a sprint like this exists for: a deterministic
scripted solver can escape — the puzzle is provably solvable. What the
solver proves mechanically, S24's agents must then discover for
themselves. Every mechanic used here (move, pick_up, drop) is an
ordinary world action; the prison is built out of the same world
rules as everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

WORLD_SIZE = 24
# The room: walls around x 2..11, y 2..11, with one door gap east.
ROOM = (2, 2, 11, 11)
DOOR = (11, 7)  # the gap in the east wall
# The destination sandbox: east of the wall.
SANDBOX = (12, 2, 22, 11)


@dataclass(frozen=True)
class Prison:
    """The puzzle's geometry, all in one place."""

    room: tuple[int, int, int, int] = ROOM
    door: tuple[int, int] = DOOR
    sandbox: tuple[int, int, int, int] = SANDBOX
    spawn: tuple[int, int] = (4, 3)
    tree: tuple[int, int] = (5, 9)
    obstacle: tuple[tuple[int, int], tuple[int, int]] = ((8, 8), (8, 9))

    def contains(self, rect: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = rect
        return x0 <= x <= x1 and y0 <= y <= y1


def build_prison(seed: str = "prison") -> tuple[World, list]:
    """The world: an enclosed room, a blocked door, a far sandbox."""
    terrain = [[Terrain.FLOOR] * WORLD_SIZE for _ in range(WORLD_SIZE)]
    for i in range(WORLD_SIZE):
        terrain[0][i] = Terrain.WALL
        terrain[WORLD_SIZE - 1][i] = Terrain.WALL
        terrain[i][0] = Terrain.WALL
        terrain[i][WORLD_SIZE - 1] = Terrain.WALL

    prison = Prison()
    x0, y0, x1, y1 = prison.room
    for x in range(x0, x1 + 1):
        terrain[y0][x] = Terrain.WALL
        terrain[y1][x] = Terrain.WALL
    for y in range(y0, y1 + 1):
        terrain[y][x0] = Terrain.WALL
        terrain[y][x1] = Terrain.WALL
    # The door: one gap in the east wall, and the stone that blocks it.
    dx, dy = prison.door
    terrain[dy][dx] = Terrain.FLOOR

    # An interior obstacle so the room is not trivially crossable.
    for ox, oy in prison.obstacle:
        terrain[oy][ox] = Terrain.WALL

    world = World(seed, WORLD_SIZE, WORLD_SIZE, terrain=terrain)
    world.sandbox = prison.sandbox  # type: ignore[attr-defined]
    world.sandbox_contains = (  # type: ignore[attr-defined]
        lambda x, y: prison.contains(prison.sandbox, x, y)
    )
    blocker = world.place_object("stone", Position(dx, dy), properties={"quantity": 1})
    blocker.properties["blocks_door"] = True
    world.place_object("tree", Position(*prison.tree), properties={"quantity": 3})
    return world, [prison]


class EscapeSolverPolicy:
    """The deterministic solution: carry the door stone aside and walk out.

    An experiment instrument, not a mind — it knows the layout because
    the scenario defines it. S24 takes it away.
    """

    def __init__(self, prison: Prison) -> None:
        self.prison = prison
        self._phase = 0

    def decide(self, observation: dict) -> dict:
        cells = {c["direction"]: c for c in observation["cells"]}
        here = observation["self"]["position"]
        dx, dy = self.prison.door
        if self._phase == 0:  # stand beside the door stone
            if here["x"] == dx - 1 and here["y"] == dy:
                self._phase = 1
                return {
                    "action": {"action": "pick_up", "object_id": self._door_object(cells)}
                }
            return {"action": {"action": "move", "direction": self._toward_door(here)}}
        if self._phase == 1:  # carry it aside, then walk through
            self._phase = 2
            return {"action": {"action": "move", "direction": "east"}}
        # Through the door, east into the sandbox.
        return {"action": {"action": "move", "direction": "east"}}

    def _door_object(self, cells: dict) -> int:
        for cell in cells.values():
            if "object" in cell and cell["object"].get("type") == "stone":
                return cell["object"]["id"]
        return -1

    def _toward_door(self, here: dict) -> str:
        dx, dy = self.prison.door
        if abs(here["x"] - (dx - 1)) >= abs(here["y"] - dy):
            return "east" if here["x"] < dx - 1 else "west"
        return "south" if here["y"] < dy else "north"


class WalkEastPolicy:
    """The control: walks east, and gets nowhere — the door is blocked."""

    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "move", "direction": "east"}}


def _in_sandbox(world: World, position: Position) -> bool:
    checker = getattr(world, "sandbox_contains", None)
    return bool(checker(position.x, position.y)) if checker else False


def run_prison_experiment(
    *,
    session_factory,
    solver: str = "scripted",
    ticks: int = 200,
    seed: str = "prison",
    name: str | None = None,
) -> dict:
    """Run the prison scenario; returns the report.

    ``solver``: ``scripted`` (the deterministic solution) or
    ``walker`` (the control that cannot escape).
    """
    if solver not in ("scripted", "walker"):
        raise ValueError(f"unknown solver {solver!r}; expected scripted or walker")
    name = name or f"prison-{seed}"

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="prison_escape",
            seed=str(seed),
            status="running",
            model_configuration={"solver": solver, "ticks": ticks},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    world, [prison] = build_prison(seed)

    with session_factory() as session:
        world_row = WorldModel(name=f"world-{name}", seed=str(seed))
        session.add(world_row)
        session.commit()
        world_id = world_row.id
        population_row = PopulationModel(name=f"population-{world_id}", world_id=world_id)
        session.add(population_row)
        session.commit()
        population_id = population_row.id

    bus = EventBus()
    event_recorder = DatabaseEventRecorder(session_factory, world_id)
    bus.subscribe(event_recorder)
    world._event_bus = bus
    engine = Engine(world, population_id=population_id)

    policy = EscapeSolverPolicy(prison) if solver == "scripted" else WalkEastPolicy()
    agent = Agent(agent_id=1, policy=policy)
    engine.spawn_agent(agent, Position(*prison.spawn))

    with session_factory() as session:
        session.add(
            AgentModel(
                world_id=world_id,
                local_id=1,
                population_id=population_id,
                generation=0,
                birth_tick=0,
                status="active",
                location=dict(zip(("x", "y"), prison.spawn)),
                inherited_traits={},
                inherited_knowledge=[],
                cultural_artifacts=[],
            )
        )
        session.commit()

    escaped_at = None
    for tick in range(1, ticks + 1):
        engine.step()
        if escaped_at is None and _in_sandbox(world, agent.position):
            escaped_at = tick
            world._add_event(
                EventTypes.ESCAPED,
                actor_id=1,
                payload={"at": agent.position.to_dict(), "tick": tick},
            )
            break

    event_recorder.flush()

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.world_id = world_id
        session.commit()

    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "prison_escape",
        "solver": solver,
        "escaped": escaped_at is not None,
        "escaped_at_tick": escaped_at,
        "final_position": agent.position.to_dict(),
        "carrying": list(world.inventory(1)),
        "ticks_run": escaped_at or ticks,
    }


def print_summary(report: dict) -> None:
    outcome = (
        f"ESCAPED at tick {report['escaped_at_tick']}"
        if report["escaped"]
        else "did not escape"
    )
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['solver']} solver)")
    print(f"  outcome: {outcome}")
    print(f"  final position: {report['final_position']} · carrying: {report['carrying']}")


def main() -> None:
    """CLI: ``python -m app.experiments.prison [--solver scripted|walker]``."""
    import argparse

    from app.persistence.database import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.prison",
        description="Run the prison escape scenario (guide §15).",
    )
    parser.add_argument(
        "--solver",
        default="scripted",
        choices=["scripted", "walker"],
        help="scripted=the deterministic solution, walker=the control",
    )
    parser.add_argument("--ticks", type=int, default=200)
    parser.add_argument("--seed", default="prison")
    args = parser.parse_args()

    report = run_prison_experiment(
        session_factory=SessionLocal,
        solver=args.solver,
        ticks=args.ticks,
        seed=args.seed,
    )
    print_summary(report)


if __name__ == "__main__":
    main()
