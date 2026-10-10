"""Agent escape: the same prison, no scripted solution (roadmap S24).

S23 proved the puzzle solvable. This sprint takes the script away:
the agent is given the objective — escape the room — and must attempt
it with nothing but the world's ordinary actions. Exploration, failed
attempts and the solution are all recorded; the escape counts only as
the simulated transition, never through a host-level shortcut.
"""

from __future__ import annotations

import json
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
from app.simulation.policies import WanderPolicy
from app.experiments.prison import (
    EscapeSolverPolicy,
    Prison,
    WalkEastPolicy,
    build_prison,
)

ESCAPE_SYSTEM_PROMPT = (
    "You are an agent trapped in a walled room with one door. Your "
    "objective: ESCAPE. Reply with JSON only, in this shape: "
    '{"action": {"action": "move|look|inspect|pick_up|drop", '
    '"direction": "north|south|east|west", "object_id": int}, '
    '"thought_summary": string|null, "message": string|null}. '
    "Your observation already shows the cells immediately around you; "
    "looking again reveals nothing new - to see more you must MOVE. "
    "Explore systematically: try each direction, remember what you "
    "tried (your memory lists your recent actions), and when you find "
    "an object standing in your way, you can pick it up and carry it. "
    "The world validates every action; an illegal action is rejected "
    "and never changes the world."
)


class MockEscapePolicy:
    """A mock mind for the runner: wanders, never solves (a control)."""

    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "look"}}


def _metrics(world, actor_id: int, explored: set, escaped_tick, ticks_run: int) -> dict:
    actions = [e for e in world.events if e.type.startswith("ACTION_") and e.actor_id == actor_id]
    return {
        "escaped": escaped_tick is not None,
        "escaped_at_tick": escaped_tick,
        "actions_attempted": len(actions),
        "actions_rejected": sum(
            1 for a in actions if a.type == EventTypes.ACTION_REJECTED
        ),
        "cells_explored": len(explored),
        "ticks_run": ticks_run,
    }


def run_escape_experiment(
    *,
    session_factory,
    solver: str = "mock",
    ticks: int = 60,
    seed: str = "escape",
    name: str | None = None,
    provider=None,
) -> dict:
    """Run the escape attempt; returns the report.

    ``solver``: ``mock`` (a wandering control), ``walker`` (walks east,
    fails), ``scripted`` (S23's deterministic solution — kept as the
    regression reference) or ``model`` (a live mind through the escape
    system prompt; pass ``provider``).
    """
    if solver not in ("mock", "walker", "scripted", "model"):
        raise ValueError(f"unknown solver {solver!r}")
    if solver == "model" and provider is None:
        raise ValueError("the model solver needs a provider")
    name = name or f"escape-{seed}"

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="agent_escape",
            seed=str(seed),
            status="running",
            model_configuration={"solver": solver, "ticks": ticks},
            compute_budget={"max_model_calls": ticks if solver == "model" else 0},
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

    if solver == "scripted":
        policy = EscapeSolverPolicy(prison)
    elif solver == "walker":
        policy = WalkEastPolicy()
    elif solver == "model":
        policy = ModelPolicy(provider, system_prompt=ESCAPE_SYSTEM_PROMPT)
    else:
        policy = MockEscapePolicy()

    agent = Agent(agent_id=1, policy=policy)
    engine.spawn_agent(agent, _spawn_position(prison))

    with session_factory() as session:
        session.add(
            AgentModel(
                world_id=world_id,
                local_id=1,
                population_id=population_id,
                generation=0,
                birth_tick=0,
                status="active",
                location=_spawn_position(prison).to_dict(),
                inherited_traits={},
                inherited_knowledge=[],
                cultural_artifacts=[],
            )
        )
        session.commit()

    import asyncio

    def _in_sandbox(position) -> bool:
        checker = getattr(world, "sandbox_contains", None)
        return bool(checker(position.x, position.y)) if checker else False

    explored = set()
    escaped_tick = None

    async def _drive() -> None:
        nonlocal escaped_tick
        for tick in range(1, ticks + 1):
            await engine.step_async()
            explored.add((agent.position.x, agent.position.y))
            if _in_sandbox(agent.position):
                escaped_tick = tick
                world._add_event(
                    EventTypes.ESCAPED,
                    actor_id=1,
                    payload={"at": agent.position.to_dict(), "tick": tick},
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

    report = {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "agent_escape",
        "solver": solver,
        "final_position": agent.position.to_dict(),
        "carrying": list(world.inventory(1)),
    }
    report.update(
        _metrics(world, 1, explored, escaped_tick, escaped_tick or ticks)
    )
    return report


def _spawn_position(prison: Prison):
    from app.simulation.world import Position

    return Position(*prison.spawn)


def print_summary(report: dict) -> None:
    outcome = (
        f"ESCAPED at tick {report['escaped_at_tick']}"
        if report["escaped"]
        else "did not escape"
    )
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['solver']} solver)")
    print(f"  outcome: {outcome}")
    print(
        f"  attempted {report['actions_attempted']} actions "
        f"({report['actions_rejected']} rejected), explored "
        f"{report['cells_explored']} cells, carrying {report['carrying']}"
    )


def main() -> None:
    """CLI: ``python -m app.experiments.escape [--solver mock|walker|scripted|model]``."""
    import argparse

    from app.persistence.database import SessionLocal

    from app.models.config import provider_from_settings

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.escape",
        description="Run the agent escape attempt (roadmap S24).",
    )
    parser.add_argument(
        "--solver",
        default="mock",
        choices=["mock", "walker", "scripted", "model"],
        help="mock=wandering control, walker=walks east, "
        "scripted=S23's solution, model=a live mind",
    )
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--seed", default="escape")
    args = parser.parse_args()

    report = run_escape_experiment(
        session_factory=SessionLocal,
        solver=args.solver,
        ticks=args.ticks,
        seed=args.seed,
        provider=provider_from_settings() if args.solver == "model" else None,
    )
    print_summary(report)


if __name__ == "__main__":
    main()
