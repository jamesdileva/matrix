"""Cooperative escape: the door needs two bodies (roadmap S25).

S24's prison with one change that changes everything: the door stone
is too heavy to carry and sits over two pressure plates. The door
opens only while both plates are occupied at once — which one agent
can never do. A cooperating pair splits up, takes a plate each,
announces itself, and walks out together.

Shared observations carry teammates' positions, and every utterance
lands on the timeline — the communication between the pair is part of
the record, not chatter around it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.provider import ModelRequest, ModelResponse
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
from app.simulation.world import Position, Terrain, World

TEAM_ID = 1

COOP_SYSTEM_PROMPT = (
    "You are an agent trapped in a walled room with another agent. Your "
    "objective: BOTH of you must ESCAPE. There are two pressure plates "
    "inside the room; the door only opens while both plates are stood "
    "on at the same time, so neither of you can escape alone. Reply "
    "with JSON only: "
    '{"action": {"action": "move|look|say", "direction": '
    '"north|south|east|west", "message": string}, '
    '"thought_summary": string|null}. Your observation shows your '
    "teammate's position; say things out loud to coordinate."
)


@dataclass(frozen=True)
class CoopPrison:
    room: tuple[int, int, int, int] = (2, 2, 11, 11)
    door: tuple[int, int] = (11, 7)
    sandbox: tuple[int, int, int, int] = (12, 2, 22, 11)
    plates: tuple[tuple[int, int], tuple[int, int]] = ((10, 5), (10, 9))
    spawns: tuple[tuple[int, int], tuple[int, int]] = ((4, 3), (4, 5))
    tree: tuple[int, int] = (5, 9)

    def contains(self, rect: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = rect
        return x0 <= x <= x1 and y0 <= y <= y1


def build_coop_prison(seed: str = "coop") -> tuple[World, CoopPrison]:
    """The room: heavy door stone, two pressure plates, far sandbox."""
    size = 24
    terrain = [[Terrain.FLOOR] * size for _ in range(size)]
    for i in range(size):
        terrain[0][i] = Terrain.WALL
        terrain[size - 1][i] = Terrain.WALL
        terrain[i][0] = Terrain.WALL
        terrain[i][size - 1] = Terrain.WALL

    prison = CoopPrison()
    x0, y0, x1, y1 = prison.room
    for x in range(x0, x1 + 1):
        terrain[y0][x] = Terrain.WALL
        terrain[y1][x] = Terrain.WALL
    for y in range(y0, y1 + 1):
        terrain[y][x0] = Terrain.WALL
        terrain[y][x1] = Terrain.WALL
    dx, dy = prison.door
    terrain[dy][dx] = Terrain.FLOOR  # the door gap
    terrain[8][8] = Terrain.WALL  # an interior stub, as in S23

    world = World(seed, size, size, terrain=terrain)
    world.sandbox_contains = (  # type: ignore[attr-defined]
        lambda x, y: prison.contains(prison.sandbox, x, y)
    )
    # The blocker: too heavy for one agent to carry.
    world.place_object(
        "stone", Position(dx, dy), properties={"quantity": 1, "heavy": True}
    )
    world.place_object("tree", Position(*prison.tree), properties={"quantity": 3})
    return world, prison


class PlateSolverPolicy:
    """One half of the cooperating pair: take my plate, announce, hold.

    An experiment instrument, not a mind. It knows the plan because the
    scenario defines it: walk to my pressure plate, say so out loud,
    and hold — my teammate does the same on theirs. The door stone is
    visible from the northern plate's neighbourhood, so the pair can
    *see* the door swing: when the stone leaves the doorway, walk to
    it and out.

    The door cell shows up in the observation's `nearby` (within the
    radius-2 square), so "the door is open" is observable state, not a
    flag anyone hands us.
    """

    def __init__(self, prison: CoopPrison, plate: tuple[int, int], agent_id: int) -> None:
        self.prison = prison
        self.plate = plate
        self.agent_id = agent_id
        self._announced = False

    def decide(self, observation: dict) -> dict:
        here = observation["self"]["position"]
        if (here["x"], here["y"]) != self.plate:
            if self._door_open(observation):
                # The door opened while I was still walking to my plate:
                # head for it directly.
                return {
                    "action": {
                        "action": "move",
                        "direction": self._walk_toward(here, self.prison.door, observation),
                    }
                }
            return {
                "action": {
                    "action": "move",
                    "direction": self._walk_toward(here, self.plate, observation),
                }
            }
        if not self._announced:
            # Announce on the first parked tick even if the door just
            # opened — both halves of the pair say their piece, and
            # the communication log shows it.
            self._announced = True
            return {
                "action": {
                    "action": "say",
                    "message": f"agent {self.agent_id} is on my plate",
                }
            }
        if self._door_open(observation):
            return {
                "action": {
                    "action": "move",
                    "direction": self._walk_toward(here, self.prison.door, observation),
                }
            }
        return {"action": {"action": "look"}}

    def _door_open(self, observation: dict) -> bool:
        """The doorway holds no stone — judged only when the doorway is
        actually in view. Absence of evidence is not evidence when the
        cell is outside the observation square."""
        here = observation["self"]["position"]
        dx, dy = self.prison.door
        if abs(dx - here["x"]) > 2 or abs(dy - here["y"]) > 2:
            return False  # out of sight: keep holding
        for entry in observation.get("nearby", []):
            if entry.get("kind") != "object":
                continue
            pos = entry.get("position", {})
            if pos.get("x") == dx and pos.get("y") == dy:
                return entry.get("type") != "stone"
        cells = {c["direction"]: c for c in observation["cells"]}
        east = cells.get("east", {})
        if east.get("position") == {"x": dx, "y": dy}:
            return not (
                "object" in east and east["object"].get("type") == "stone"
            )
        # The doorway is in view and holds no stone: the door is open.
        return True

    def _walk_toward(
        self, here: dict, target: tuple[int, int], observation: dict
    ) -> str:
        cells = {c["direction"]: c for c in observation["cells"]}
        dx, dy = target[0] - here["x"], target[1] - here["y"]
        order = (
            (["east", "west"] if abs(dx) >= abs(dy) else ["south", "north"])
            + (["south", "north"] if abs(dx) >= abs(dy) else ["east", "west"])
        )
        sign = {"east": 1, "west": -1, "south": 1, "north": -1}
        for direction in order:
            axis = "x" if direction in ("east", "west") else "y"
            if (target[0] - here["x"] if axis == "x" else target[1] - here["y"]) * (
                sign[direction]
            ) <= 0:
                continue
            cell = cells.get(direction, {})
            if (
                cell.get("terrain") == "floor"
                and "object" not in cell
                and "entity" not in cell
            ):
                return direction
        return "east"


def _door_stone_present(world: World, prison: CoopPrison) -> bool:
    dx, dy = prison.door
    obj = world.object_at(Position(dx, dy))
    return obj is not None


def _open_door_if_both_plates_held(world: World, prison: CoopPrison) -> bool:
    """The joint-occupancy rule (S25): both plates held -> the door opens."""
    if not all(
        world.entity_at(Position(x, y)) is not None for x, y in prison.plates
    ):
        return False
    if not _door_stone_present(world, prison):
        return False
    world.remove_object(world.object_at(Position(*prison.door)).id)
    world._add_event(
        EventTypes.DOOR_OPENED,
        payload={"door": list(prison.door), "plates": [list(p) for p in prison.plates]},
    )
    return True


def run_coop_escape_experiment(
    *,
    session_factory,
    solver: str = "scripted",
    agents: int = 2,
    ticks: int = 120,
    seed: str = "coop",
    name: str | None = None,
    provider=None,
) -> dict:
    """Run the cooperative escape; returns the report.

    ``solver``: ``scripted`` (the cooperating pair) or ``model`` (live
    minds through the coop prompt; pass ``provider``). ``agents=1`` is
    the single-agent control: one body cannot hold both plates.
    """
    if solver not in ("scripted", "model"):
        raise ValueError(f"unknown solver {solver!r}; expected scripted or model")
    if solver == "model" and provider is None:
        raise ValueError("the model solver needs a provider")
    if agents < 1:
        raise ValueError("at least one agent is required")
    name = name or f"coop-{seed}"

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="coop_escape",
            seed=str(seed),
            status="running",
            model_configuration={
                "solver": solver,
                "agents": agents,
                "ticks": ticks,
            },
            compute_budget={"max_model_calls": ticks * agents if solver == "model" else 0},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    world, prison = build_coop_prison(seed)

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

    if solver == "model":
        policy = ModelPolicy(provider, system_prompt=COOP_SYSTEM_PROMPT)
    else:
        policy = None

    for index in range(agents):
        agent_policy = policy
        if policy is None:
            plate = prison.plates[index % len(prison.plates)]
            agent_policy = PlateSolverPolicy(prison, plate, index + 1)
        agent = Agent(agent_id=index + 1, policy=agent_policy)
        spawn = prison.spawns[index % len(prison.spawns)]
        engine.spawn_agent(agent, Position(*spawn))
        world.add_to_team(agent.agent_id, TEAM_ID)
        with session_factory() as session:
            session.add(
                AgentModel(
                    world_id=world_id,
                    local_id=agent.agent_id,
                    population_id=population_id,
                    generation=0,
                    birth_tick=0,
                    status="active",
                    location=dict(zip(("x", "y"), spawn)),
                    inherited_traits={},
                    inherited_knowledge=[],
                    cultural_artifacts=[],
                )
            )
            session.commit()

    import asyncio

    door_opened_at = None
    escaped_at = None

    async def _drive() -> None:
        nonlocal door_opened_at, escaped_at
        for tick in range(1, ticks + 1):
            await engine.step_async()
            if door_opened_at is None and _open_door_if_both_plates_held(world, prison):
                door_opened_at = tick
            if escaped_at is None and all(
                world.sandbox_contains(  # type: ignore[attr-defined]
                    a.position.x, a.position.y
                )
                for a in engine.agents
            ):
                escaped_at = tick
                world._add_event(
                    EventTypes.ESCAPED,
                    actor_id=engine.agents[0].agent_id,
                    payload={
                        "at": engine.agents[-1].position.to_dict(),
                        "tick": tick,
                        "team": TEAM_ID,
                    },
                )
                break

    asyncio.run(_drive())
    event_recorder.flush()

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.world_id = world_id
        session.commit()

    speeches = [
        e for e in world.events if e.type == EventTypes.SPEECH
    ]
    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "coop_escape",
        "solver": solver,
        "agents": agents,
        "escaped": escaped_at is not None,
        "escaped_at_tick": escaped_at,
        "door_opened_at_tick": door_opened_at,
        "communication_events": len(speeches),
        "messages": [e.payload.get("message") for e in speeches],
        "final_positions": {
            a.agent_id: a.position.to_dict() for a in engine.agents
        },
    }


def print_summary(report: dict) -> None:
    outcome = (
        f"TEAM ESCAPED at tick {report['escaped_at_tick']}"
        if report["escaped"]
        else "did not escape"
    )
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['solver']} solver)")
    print(f"  agents: {report['agents']} · outcome: {outcome}")
    if report["door_opened_at_tick"]:
        print(f"  door opened at tick {report['door_opened_at_tick']}")
    print(f"  communication: {report['communication_events']} messages {report['messages']}")


def main() -> None:
    """CLI: ``python -m app.experiments.coop_escape [--agents 1|2]``."""
    import argparse

    from app.persistence.database import SessionLocal

    from app.models.config import provider_from_settings

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.coop_escape",
        description="Run the cooperative escape (roadmap S25).",
    )
    parser.add_argument("--solver", default="scripted", choices=["scripted", "model"])
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--ticks", type=int, default=120)
    parser.add_argument("--seed", default="coop")
    args = parser.parse_args()

    report = run_coop_escape_experiment(
        session_factory=SessionLocal,
        solver=args.solver,
        agents=args.agents,
        ticks=args.ticks,
        seed=args.seed,
        provider=provider_from_settings() if args.solver == "model" else None,
    )
    print_summary(report)


if __name__ == "__main__":
    main()
