"""S46 — observer vs participant: one world, two histories.

The question is deliberately simple: if two worlds start from the same
seed and the same recipe, and a human enters only one of them, what changes?
This module runs that pair. The observer world is left alone; in the
participant world a body joins a population, teaches one agent, gives it a
task, introduces objects, speaks, and lets nearby agents learn the words.

Every measure is a count read off the finished world, grouped into the five
dimensions the roadmap asks about: development, culture, behaviour,
technology and communication. The comparison is a matched pair, not a
statistical claim: same seed, same template, same span, one difference.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.host import PARTICIPANT_ENTITY_ID
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.interventions import world_metrics
from app.simulation.technology import is_technology
from app.simulation.world import SPEECH_RADIUS, Position, World

from app.experiments.multi_world import (
    WorldTemplate,
    _policy,
    _spawn_spots,
    export_study,
    resolve_template,
)

SCENARIO = "observer_vs_participant"

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "development": (
        "entities",
        "population",
        "births",
        "objects",
        "resources",
        "structures",
        "settlements",
        "challenges_completed",
    ),
    "culture": (
        "knowledge_facts",
        "artifacts",
        "games",
        "vocabulary",
        "shared_words",
    ),
    "behavior": (
        "actions",
        "moves",
        "gathers",
        "builds",
        "transfers",
        "follows",
        "rejections",
        "participant_actions",
    ),
    "technology": (
        "known_recipes",
        "known_patterns",
        "discoveries",
        "inventions",
        "crafts",
    ),
    "communication": (
        "speech",
        "direct",
        "announce",
        "broadcast",
        "deliveries",
        "words_invented",
        "words_adopted",
        "agreement",
    ),
}

MEASURES = tuple(
    measure for measures in DIMENSIONS.values() for measure in measures
)

DEFAULT_FACTS = ("water is life", "stone is heavy", "recipe:door")
DEFAULT_TASK = "build a shelter before winter"
DEFAULT_OBJECTS = (("monument", 1), ("tree", 4))
DEFAULT_MESSAGE = "water stone tree fire food home path door"


@dataclass(frozen=True)
class ParticipantPlan:
    """What the human does on the first tick of the participant world."""

    population_id: int | None = 1
    facts: tuple[str, ...] = DEFAULT_FACTS
    task: str = DEFAULT_TASK
    objects: tuple[tuple[str, int], ...] = DEFAULT_OBJECTS
    message: str = DEFAULT_MESSAGE
    teach: bool = True

    def to_dict(self) -> dict:
        return {
            "population_id": self.population_id,
            "facts": list(self.facts),
            "task": self.task,
            "objects": [
                {"type": object_type, "quantity": quantity}
                for object_type, quantity in self.objects
            ],
            "message": self.message,
            "teach": self.teach,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParticipantPlan":
        objects = tuple(
            (str(item["type"]), int(item.get("quantity", 1)))
            if isinstance(item, dict)
            else (str(item[0]), int(item[1]))
            for item in data.get("objects", DEFAULT_OBJECTS)
        )
        return cls(
            population_id=data.get("population_id", 1),
            facts=tuple(data.get("facts", DEFAULT_FACTS)),
            task=str(data.get("task", DEFAULT_TASK)),
            objects=objects,
            message=str(data.get("message", DEFAULT_MESSAGE)),
            teach=bool(data.get("teach", True)),
        )


def _nearest_floor(
    world: World, origin: Position, *, avoid_entities: bool = True
) -> Position | None:
    # entity_positions() maps id -> Position; the *values* are the blocked cells.
    blocked = set(world.entity_positions().values()) if avoid_entities else set()
    candidates = [
        Position(x, y)
        for y in range(world.height)
        for x in range(world.width)
        if world.is_floor(Position(x, y))
        and world.object_at(Position(x, y)) is None
        and Position(x, y) not in blocked
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda cell: (
            abs(cell.x - origin.x) + abs(cell.y - origin.y),
            cell.y,
            cell.x,
        ),
    )


def _alive(agents: Iterable[Agent]) -> list[Agent]:
    return [
        agent
        for agent in agents
        if agent.status == "alive" and agent.position is not None
    ]


def apply_participant_plan(
    world: World,
    agents: Iterable[Agent],
    plan: ParticipantPlan,
) -> dict:
    """Carry out the human's first tick and report every effect."""
    here = world.entity_position(PARTICIPANT_ENTITY_ID)
    if here is None:
        raise ValueError("participant is not in the world")
    living = _alive(agents)
    applied: dict = {
        "participant_id": PARTICIPANT_ENTITY_ID,
        "position": here.to_dict(),
        "population_id": world.population_of(PARTICIPANT_ENTITY_ID),
        "facts": [],
        "technology": [],
        "task": None,
        "objects": [],
        "speech": None,
        "listeners": [],
    }

    target = living[0] if living else None
    if target is not None:
        for item in plan.facts:
            if item not in target.knowledge:
                target.knowledge.append(item)
            granted = world.grant_knowledge(target.agent_id, [item])
            applied["technology"].extend(
                item for item in granted if is_technology(item)
            )
            applied["facts"].append(item)
        if plan.task:
            target.goal = plan.task
            applied["task"] = plan.task

    for object_type, quantity in plan.objects:
        if quantity <= 0:
            continue
        spot = _nearest_floor(world, here)
        if spot is None:
            break
        obj = world.place_object(
            object_type,
            spot,
            properties={"quantity": int(quantity)},
            created_by_agent_id=PARTICIPANT_ENTITY_ID,
        )
        applied["objects"].append(
            {
                "object_id": obj.id,
                "type": obj.type,
                "quantity": int(quantity),
                "position": obj.position.to_dict(),
            }
        )

    if plan.message:
        event = world.speak(PARTICIPANT_ENTITY_ID, plan.message)
        applied["speech"] = {
            "event_id": event.id,
            "text": event.payload.get("text"),
            "symbols": dict(event.payload.get("symbols") or {}),
        }
        if plan.teach:
            for agent in living:
                position = world.entity_position(agent.agent_id)
                if position is None:
                    continue
                distance = abs(position.x - here.x) + abs(position.y - here.y)
                if distance > SPEECH_RADIUS:
                    continue
                changes = world.learn(agent.agent_id, PARTICIPANT_ENTITY_ID)
                if changes:
                    applied["listeners"].append(
                        {"agent_id": agent.agent_id, "learned": len(changes)}
                    )

    applied["actions"] = (
        len(applied["facts"])
        + (1 if applied["task"] else 0)
        + len(applied["objects"])
        + (1 if applied["speech"] else 0)
        + (1 if applied["population_id"] is not None else 0)
    )
    return applied


def measure_world(
    world: World,
    agents: Iterable[Agent],
    *,
    participant_actions: int = 0,
) -> dict:
    """Every dimension's measures, read off a finished world."""
    base = world_metrics(world, agents)
    verbs: dict[str, int] = {}
    births = artifacts = 0
    transfers = follows = 0
    speech = direct = announce = broadcast = deliveries = 0
    words_invented = words_adopted = 0
    discoveries = inventions = crafts = 0
    for event in world.events:
        if event.type == EventTypes.AGENT_BORN:
            births += 1
        elif event.type == EventTypes.ARTIFACT_CREATED:
            artifacts += 1
        elif event.type == EventTypes.ACTION_EXECUTED:
            action = event.payload.get("action") or {}
            verb = action.get("action") if isinstance(action, dict) else None
            if verb:
                verbs[verb] = verbs.get(verb, 0) + 1
        elif event.type == EventTypes.TRANSFER:
            transfers += 1
        elif event.type == EventTypes.FOLLOW:
            follows += 1
        elif event.type == EventTypes.SPEECH:
            speech += 1
        elif event.type == EventTypes.DIRECT:
            direct += 1
            deliveries += len(event.payload.get("recipients") or ())
        elif event.type == EventTypes.ANNOUNCE:
            announce += 1
            deliveries += len(event.payload.get("recipients") or ())
        elif event.type == EventTypes.BROADCAST:
            broadcast += 1
            deliveries += len(event.payload.get("recipients") or ())
        elif event.type == EventTypes.WORD_INVENTED:
            words_invented += 1
        elif event.type == EventTypes.WORD_ADOPTED:
            words_adopted += 1
        elif event.type == EventTypes.INVENTION:
            if event.payload.get("kind") == "discovery":
                discoveries += 1
            else:
                inventions += 1
        elif event.type == EventTypes.CRAFT:
            crafts += 1

    language = world.language_summary()
    measures = {
        **base,
        "births": births,
        "structures": len(world.structures()),
        "artifacts": artifacts,
        "vocabulary": sum(agent["concepts"] for agent in language["agents"]),
        "shared_words": len(language["shared_words"]),
        "agreement": language["agreement"],
        "actions": sum(verbs.values()),
        "moves": verbs.get("move", 0),
        "gathers": verbs.get("gather", 0),
        "builds": verbs.get("build", 0),
        "transfers": transfers,
        "follows": follows,
        "rejections": base.get("rejections", 0),
        "participant_actions": participant_actions,
        "discoveries": discoveries,
        "inventions": inventions,
        "crafts": crafts,
        "speech": speech,
        "direct": direct,
        "announce": announce,
        "broadcast": broadcast,
        "deliveries": deliveries,
        "words_invented": words_invented,
        "words_adopted": words_adopted,
    }
    measures["rejections"] = sum(
        1 for event in world.events if event.type == EventTypes.ACTION_REJECTED
    )
    return {measure: measures[measure] for measure in MEASURES}


def run_world(
    template: WorldTemplate,
    seed: str,
    *,
    ticks: int | None = None,
    participant: bool = False,
    plan: ParticipantPlan | None = None,
) -> dict:
    """Run one side of the pair and report its measures."""
    if ticks is not None and ticks < 0:
        raise ValueError(f"ticks must be non-negative, got {ticks}")
    span = template.ticks if ticks is None else ticks
    chosen_plan = (plan or ParticipantPlan()) if participant else None

    world = World.generate(str(seed), template.width, template.height)
    engine = Engine(world, population_id=1)
    policies = [_policy(name) for name in (template.policies or ("wander",))]
    spots = _spawn_spots(world, template.agents)
    for index, spot in enumerate(spots):
        engine.spawn_agent(
            Agent(
                agent_id=index + 1,
                policy=policies[index % len(policies)],
                observation_radius=3,
            ),
            spot,
        )

    applied = None
    actions = 0
    if chosen_plan is not None:
        anchor = spots[0] if spots else Position(world.width // 2, world.height // 2)
        spot = _nearest_floor(world, anchor)
        if spot is None:
            raise ValueError("participant world has no free floor for the participant")
        world.add_entity(PARTICIPANT_ENTITY_ID, spot)
        if chosen_plan.population_id is not None:
            world.set_population(PARTICIPANT_ENTITY_ID, chosen_plan.population_id)
        applied = apply_participant_plan(world, engine.agents, chosen_plan)
        actions = applied["actions"]

    for _ in range(span):
        engine.step()

    return {
        "template": template.name,
        "seed": str(seed),
        "ticks": span,
        "role": "participant" if participant else "observer",
        "participant": applied,
        "measures": measure_world(
            world, engine.agents, participant_actions=actions
        ),
    }


def compare_runs(observer: dict, participant: dict) -> dict:
    """The paired difference, grouped by the five dimensions."""
    dimensions = {}
    differing: list[str] = []
    for dimension, names in DIMENSIONS.items():
        left = {name: observer["measures"][name] for name in names}
        right = {name: participant["measures"][name] for name in names}
        delta = {name: right[name] - left[name] for name in names}
        changed = [name for name in names if delta[name] != 0]
        differing.extend(changed)
        dimensions[dimension] = {
            "observer": left,
            "participant": right,
            "delta": delta,
            "changed": changed,
        }
    return {
        "dimensions": dimensions,
        "differing": sorted(set(differing)),
        "identical": not differing,
    }


def run_study(
    *,
    session_factory,
    template: str = "void",
    seed: str = "observer",
    ticks: int | None = None,
    participant_plan: ParticipantPlan | None = None,
    export_path: str | None = None,
    name: str | None = None,
    experiment_id: int | None = None,
) -> dict:
    """Run the same world observed, then with a participant, and compare."""
    chosen = resolve_template(template)
    if ticks is not None and ticks < 0:
        raise ValueError(f"ticks must be non-negative, got {ticks}")
    span = chosen.ticks if ticks is None else ticks
    plan = participant_plan or ParticipantPlan()
    label = name or f"observer-{seed}"
    config = {
        "template": template,
        "ticks": ticks,
        "measures": list(MEASURES),
        "dimensions": {key: list(value) for key, value in DIMENSIONS.items()},
        "participant_plan": plan.to_dict(),
    }

    if experiment_id is None:
        with session_factory() as session:
            experiment = ExperimentModel(
                name=label,
                scenario=SCENARIO,
                seed=str(seed),
                status="running",
                model_configuration=config,
                started_at=datetime.now(timezone.utc),
            )
            session.add(experiment)
            session.commit()
            experiment_id = experiment.id
    else:
        # Queued by the API; the worker asked this study to fill its row.
        with session_factory() as session:
            row = session.get(ExperimentModel, experiment_id)
            row.status = "running"
            row.started_at = datetime.now(timezone.utc)
            row.name = label
            session.commit()

    observer = run_world(chosen, seed, ticks=span)
    participant = run_world(
        chosen, seed, ticks=span, participant=True, plan=plan
    )
    comparison = compare_runs(observer, participant)
    study = {
        "experiment_id": experiment_id,
        "name": label,
        "scenario": SCENARIO,
        "seed": str(seed),
        "template": template,
        "ticks": span,
        "measures": list(MEASURES),
        "dimensions": {key: list(value) for key, value in DIMENSIONS.items()},
        "participant_plan": plan.to_dict(),
        "observer": observer,
        "participant": participant,
        "comparison": comparison,
    }

    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {**config, "comparison": comparison}
        row.result = study
        session.commit()

    if export_path:
        study["export_path"] = export_study(study, export_path)
    return study


def print_summary(study: dict) -> None:
    print(
        f"observer vs participant {study['name']!r}: {study['template']} "
        f"for {study['ticks']} ticks from seed {study['seed']!r}"
    )
    for dimension, detail in study["comparison"]["dimensions"].items():
        changed = ", ".join(detail["changed"]) or "nothing"
        print(f"  {dimension:14s} changed: {changed}")
    print(f"  differing measures: {len(study['comparison']['differing'])}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.observer",
        description="Run one observed world and one participant world (roadmap S46).",
    )
    parser.add_argument("--template", default="void")
    parser.add_argument("--seed", default="observer")
    parser.add_argument("--ticks", type=int, default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--export", default=None, help="write the study as JSON here")
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    study = run_study(
        session_factory=SessionLocal,
        template=args.template,
        seed=args.seed,
        ticks=args.ticks,
        export_path=args.export,
        name=args.name,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
