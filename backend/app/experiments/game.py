"""S31 — a game for the human: invented, validated, played.

The roadmap's experiment in one file. A designer proposes a game —
scripted, a known-valid calibration, or a model mind inventing one
for the human through the S07 seam — and the engine judges the
proposal: valid rules open a table that two players finish; invalid
rules are refused with their reasons, which is the sprint's
verification wearing work clothes. The human's part happens live: an
invented, validated game opens on a real world, the participant takes
a seat, and plays it through the API against a scripted opponent.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.config.settings import settings
from app.models.decision import DecisionError, extract_json_object
from app.models.provider import ModelRequest
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.games import LONG_ROAD, PlayerPolicy, validate_rules
from app.simulation.world import Position, Terrain, World

GAME_SYSTEM_PROMPT = (
    "You are a game designer inside a grid world, inventing a game "
    "for the human who watches it. Reply with JSON only, in this shape: "
    '{"name": string, "description": string, "players": 2, '
    '"setup": {"counter name": 0}, '
    '"moves": {"move name": {"description": string, '
    '"requires": {"counter name": "<10"}, '
    '"effect": {"add": {"counter name": 1}, "award": 0, "again": false}}}, '
    '"win": {"first_to": {"counter name": 10}}} '
    "Rules of the shape: players is 2, setup holds only numbers, "
    "every move needs a requires comparison like \"<10\" against a "
    "setup counter and an effect that adds to one, and win is first_to "
    "a counter that some move can reach. Small and finished beats "
    "grand and unplayable."
)


async def invent_game(provider) -> dict:
    """Ask a model mind for a game; return the rules and the verdict."""
    request = ModelRequest(observation={"task": "invent a game for the human"},
                           system_prompt=GAME_SYSTEM_PROMPT)
    response = await provider.generate(request)
    try:
        data = extract_json_object(response.text)
    except DecisionError as exc:
        return {"valid": False, "rules": None, "errors": [f"unusable output: {exc}"]}
    # The prompt asks for the rules at the top level; a model that
    # wraps them under "rules" is accommodated, not punished.
    rules = data if "moves" in data else data.get("rules")
    if not isinstance(rules, dict):
        return {"valid": False, "rules": None, "errors": ["no rules mapping in the output"]}
    errors = validate_rules(rules)
    return {"valid": not errors, "rules": rules if not errors else None, "errors": errors}


def play_calibration(*, session_factory, seed: str = "table") -> dict:
    """The scripted game, played to a recorded winner (S31's control)."""
    name = f"game-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="game",
            seed=str(seed),
            status="running",
            model_configuration={"mode": "scripted"},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    world = World(
        str(seed),
        16,
        16,
        terrain=[[Terrain.FLOOR] * 16 for _ in range(16)],
    )
    engine = Engine(world, population_id=1)
    agents = []
    for index in (1, 2):
        agent = Agent(agent_id=index, policy=PlayerPolicy())
        engine.spawn_agent(agent, Position(index, index))
        agents.append(agent)

    game = world.propose_game(agents[0].agent_id, LONG_ROAD)
    session = world.open_session(game["id"])
    world.join_session(session.id, 1)
    world.join_session(session.id, 2)
    for _tick in range(1, 100):
        engine.step()
        if world.session(session.id).status == "finished":
            break
    finished = world.session(session.id)

    record = {
        "experiment_id": experiment_id,
        "mode": "scripted",
        "game": game["name"],
        "players": list(finished.players),
        "moves_played": len(finished.history),
        "winner": finished.winner,
        "win_reason": finished.win_reason,
        "final_state": dict(finished.state),
        "invented": None,
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": "scripted",
            "winner": finished.winner,
            "moves_played": len(finished.history),
        }
        session.commit()
    return record


async def invent_for_human(*, session_factory, seed: str = "for-human") -> dict:
    """The roadmap's experiment: a model mind invents a game for the human."""
    from app.models.config import provider_from_settings

    provider = provider_from_settings(settings)
    name = f"game-invent-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="game-invention",
            seed=str(seed),
            status="running",
            model_configuration={"mode": "model"},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    invention = await invent_game(provider)
    record = {
        "experiment_id": experiment_id,
        "mode": "model",
        "invented": invention,
    }
    if invention["valid"]:
        # The invented game opens immediately: the human can join it
        # live, which is the sprint's end goal in one CLI run.
        bus = EventBus()
        world = World(
            f"{seed}-table",
            16,
            16,
            terrain=[[Terrain.FLOOR] * 16 for _ in range(16)],
            event_bus=bus,
        )
        engine = Engine(world, population_id=1)
        agent = Agent(agent_id=1, policy=PlayerPolicy())
        engine.spawn_agent(agent, Position(1, 1))
        game = world.propose_game(agent.agent_id, invention["rules"])
        session = world.open_session(game["id"])
        record["game"] = game["name"]
        record["session_id"] = session.id
        record["world"] = {
            "seed": f"{seed}-table",
            "game_id": game["id"],
            "session_id": session.id,
        }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": "model",
            "valid": invention["valid"],
            "errors": invention["errors"],
        }
        session.commit()
    return record


def print_record(record: dict) -> None:
    if record["mode"] == "scripted":
        print(f"game {record['game']!r}: {record['moves_played']} moves played")
        print(f"  winner: agent {record['winner']} ({record['win_reason']})")
    else:
        invented = record["invented"]
        if not invented["valid"]:
            print("the invention was refused:")
            for error in invented["errors"]:
                print(f"  - {error}")
        else:
            print(f"invented for the human: {invented['rules']['name']!r}")
            print(f"  join it: session {record['session_id']} on a live world")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.game",
        description="Play a scripted game, or invent one for the human (roadmap S31).",
    )
    parser.add_argument("--mode", default="scripted", choices=["scripted", "model"])
    parser.add_argument("--seed", default="table")
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    if args.mode == "scripted":
        print_record(
            play_calibration(session_factory=SessionLocal, seed=args.seed)
        )
    else:
        print_record(
            asyncio.run(invent_for_human(session_factory=SessionLocal, seed=args.seed))
        )


if __name__ == "__main__":
    main()
