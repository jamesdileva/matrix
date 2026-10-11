"""S28 — the rumor: direct chains against group announcements.

One agent knows a fact. In the DIRECT condition the fact travels as a
chain of named letters — each knower tells the next agent, one hop per
tick. In the GROUP condition the knower announces once to its
population and everyone hears it at once. Same world shape, same tick
loop, same measure (ticks to inform everyone, messages sent) — the
report is the roadmap's comparison of direct communication against
group communication.

The policies are experiment instruments, not minds: they know the
fact's wording because the scenario defines it, and the chain's order
because the scenario assigns it. A knower relays on the tick *after*
learning — reading takes a beat. Without the beat the whole chain
would cascade inside a single tick (agents act in ascending id order
and observe the current inbox) and the comparison would be vacuous.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app.persistence.models import ExperimentModel, WorldModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, World

RUMOR = "the north gate stands open"

DIRECT = "direct"
GROUP = "group"
CONDITIONS = (DIRECT, GROUP)


def knows_fact(messages: list[dict]) -> bool:
    """Whether the fact reached this inbox."""
    return any(message.get("message") == RUMOR for message in messages)


class ChainPolicy:
    """One link of the rumor chain: learn, then tell the next link.

    The successor is scenario knowledge (link i tells link i+1); the
    last link has none and only listens. Relay waits a beat after
    learning, so the rumor travels one hop per tick.
    """

    def __init__(self, successor: int | None, already_knows: bool = False) -> None:
        self._successor = successor
        self._knows = already_knows
        self._known_since: int | None = None
        self._told = False

    def decide(self, observation: dict) -> dict:
        tick = observation["self"]["tick"]
        if not self._knows and knows_fact(observation["messages"]):
            self._knows = True
            self._known_since = tick
        if (
            self._knows
            and not self._told
            and self._successor is not None
            and (self._known_since is None or tick > self._known_since)
        ):
            self._told = True
            return {
                "action": {"action": "tell", "target": self._successor, "message": RUMOR}
            }
        return {"action": {"action": "look"}}


class CrierPolicy:
    """The knower who tells everyone at once: one group announcement."""

    def __init__(self, scope: str = "population", already_knows: bool = False) -> None:
        self._scope = scope
        self._knows = already_knows
        self._announced = False

    def decide(self, observation: dict) -> dict:
        if not self._knows and knows_fact(observation["messages"]):
            self._knows = True
        if self._knows and not self._announced:
            self._announced = True
            return {
                "action": {"action": "announce", "scope": self._scope, "message": RUMOR}
            }
        return {"action": {"action": "look"}}


def _build_world(seed: str, agents: int, condition: str) -> Engine:
    if agents < 2:
        raise ValueError(f"a rumor needs at least 2 agents, got {agents}")
    world = World.generate(f"{seed}-{condition}", 16, 16)
    engine = Engine(world, population_id=1)
    spots = [
        Position(x, y)
        for y in range(1, world.height - 1)
        for x in range(1, world.width - 1)
        if world.is_floor(Position(x, y)) and world.object_at(Position(x, y)) is None
    ]
    for index in range(agents):
        if condition == DIRECT:
            successor = index + 2 if index + 2 <= agents else None
            policy = ChainPolicy(successor, already_knows=index == 0)
        else:
            policy = (
                CrierPolicy(already_knows=True)
                if index == 0
                else WanderPolicy()
            )
        engine.spawn_agent(Agent(agent_id=index + 1, policy=policy), spots[index])
    return engine


def _informed(engine: Engine) -> list[bool]:
    """Who knows the fact: the first agent always does, the rest show it
    in their inbox."""
    known = []
    for agent in engine.agents:
        if agent.agent_id == 1:
            known.append(True)
        else:
            known.append(knows_fact(agent.observe()["messages"]))
    return known


def run_condition(
    *,
    session_factory,
    condition: str,
    agents: int = 5,
    seed: str = "rumor",
    max_ticks: int = 50,
) -> dict:
    """Run one condition: spread the rumor, measure the spread."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected one of {CONDITIONS}")
    name = f"rumor-{condition}-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="rumor",
            seed=str(seed),
            status="running",
            model_configuration={"condition": condition, "agents": agents},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id
        world_row = WorldModel(name=f"world-{name}", seed=str(seed))
        session.add(world_row)
        session.commit()

    engine = _build_world(seed, agents, condition)
    event_type = EventTypes.DIRECT if condition == DIRECT else EventTypes.ANNOUNCE
    informed_history: list[int] = []
    ticks_to_all: int | None = None
    for tick in range(1, max_ticks + 1):
        engine.step()
        informed = sum(_informed(engine))
        informed_history.append(informed)
        if informed == agents:
            ticks_to_all = tick
            break

    messages_sent = sum(1 for e in engine.world.events if e.type == event_type)
    record = {
        "experiment_id": experiment_id,
        "condition": condition,
        "agents": agents,
        "ticks_to_all": ticks_to_all,
        "messages_sent": messages_sent,
        "informed_history": informed_history,
    }
    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.model_configuration = {
            "condition": condition,
            "agents": agents,
            "ticks_to_all": ticks_to_all,
            "messages_sent": messages_sent,
        }
        session.commit()
    return record


def run_comparison(
    *,
    session_factory,
    agents: int = 5,
    seed: str = "rumor",
    max_ticks: int = 50,
) -> dict:
    """Both conditions, same seed: the comparison itself."""
    conditions = {
        condition: run_condition(
            session_factory=session_factory,
            condition=condition,
            agents=agents,
            seed=seed,
            max_ticks=max_ticks,
        )
        for condition in CONDITIONS
    }
    direct, group = conditions[DIRECT], conditions[GROUP]
    faster = None
    if direct["ticks_to_all"] is not None and group["ticks_to_all"] is not None:
        faster = (
            GROUP
            if group["ticks_to_all"] < direct["ticks_to_all"]
            else DIRECT
            if direct["ticks_to_all"] < group["ticks_to_all"]
            else "tie"
        )
    return {
        "agents": agents,
        "seed": seed,
        "conditions": conditions,
        "comparison": {
            "faster": faster,
            "ticks_saved": (
                direct["ticks_to_all"] - group["ticks_to_all"]
                if faster == GROUP
                else None
            ),
            "messages_saved": direct["messages_sent"] - group["messages_sent"],
        },
    }


def print_comparison(report: dict) -> None:
    for condition, record in report["conditions"].items():
        ticks = record["ticks_to_all"]
        print(
            f"  {condition}: {record['agents']} agents informed in "
            f"{ticks if ticks is not None else 'NEVER'} ticks, "
            f"{record['messages_sent']} messages sent"
        )
    comparison = report["comparison"]
    print(
        f"  group communication is {comparison['faster']} "
        f"({comparison['ticks_saved']} ticks, "
        f"{comparison['messages_saved']} messages saved)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Spread a rumor two ways; compare.")
    parser.add_argument("--condition", default="both", choices=[*CONDITIONS, "both"])
    parser.add_argument("--agents", type=int, default=5)
    parser.add_argument("--seed", default="rumor")
    parser.add_argument("--max-ticks", type=int, default=50)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    if args.condition == "both":
        print(f"rumor comparison ({args.agents} agents, seed {args.seed!r}):")
        print_comparison(
            run_comparison(
                session_factory=SessionLocal,
                agents=args.agents,
                seed=args.seed,
                max_ticks=args.max_ticks,
            )
        )
    else:
        record = run_condition(
            session_factory=SessionLocal,
            condition=args.condition,
            agents=args.agents,
            seed=args.seed,
            max_ticks=args.max_ticks,
        )
        print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
