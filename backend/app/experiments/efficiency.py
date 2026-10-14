"""S34 â€” compute efficiency: what agents accomplish per unit of compute.

Four ratios, read off machinery the earlier sprints already built â€”
the timeline (S08+) and the budget ledger (S33):

    tokens / discovery          what knowing something costs to learn
    CPU seconds / solution      what finishing a task costs to do
    messages / successful task  what coordination costs to organise
    compute / surviving concept  what culture costs to keep

Nothing here invents a meter. Discoveries, tasks and messages are
events the world already records; tokens, CPU seconds, model calls and
actions are spends the ledger already charges. A ratio with an empty
denominator is reported as ``None`` rather than a fake zero â€” a run
that learned nothing has no cost-per-discovery to report.

"Compute" in the fourth ratio is the documented composite of
everything an agent spent: tokens + model calls + actions + CPU
seconds. Kinds do not convert into each other; the composite exists so
the roadmap's single line has a single number, and the raw ledger
rides along in every record so a reader can recompute anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as stats
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import settings
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.world import Position, Terrain, World

STUDY_SCENARIO = "efficiency_study"
RUN_SCENARIO = "efficiency_campaign"

WORLD_SIZE = 20
GROVE = [(4, 4), (5, 4), (6, 4)]  # trees beside the founder's start

# The roadmap's four ratios, in its own words.
RATIOS = (
    "tokens_per_discovery",
    "cpu_seconds_per_solution",
    "messages_per_successful_task",
    "compute_per_surviving_concept",
)

MESSAGE_EVENTS = (
    EventTypes.SPEECH,
    EventTypes.DIRECT,
    EventTypes.ANNOUNCE,
    EventTypes.BROADCAST,
)


def _spend_ledger(world: World) -> dict:
    """Total spent per kind across every agent ledger and the run's.

    The action dispatcher charges each entity's own ledger and the
    experiment's shared ceiling when one exists, so a run's total is
    the union â€” reading either alone undercounts.
    """
    totals = {"tokens": 0.0, "model_calls": 0.0, "cpu_seconds": 0.0, "actions": 0.0}
    for entity_id in world.entity_ids:
        ledger = world.budget_of(entity_id).to_dict()
        for kind in totals:
            totals[kind] += ledger[kind]["spent"]
    if world.experiment_budget is not None:
        for kind in totals:
            totals[kind] += world.experiment_budget.to_dict()[kind]["spent"]
    return totals


def _ratio(numerator: float, denominator: int) -> float | None:
    """The ratio, or None when there is nothing to divide by."""
    if not denominator or numerator <= 0:
        return None
    return round(numerator / denominator, 6)


def measure_efficiency(world: World, agents: list[Agent] | None = None) -> dict:
    """Read the four ratios off one finished run's world and ledger.

    ``surviving concepts`` are the culture still standing at the end:
    every distinct recipe or pattern the world knows, plus the
    knowledge each agent carries â€” what the compute bought and the
    world still holds. Knowledge comes from the engine's agents (the
    world holds only their entity ids), so the runner passes them.
    """
    events = list(world.events)
    discoveries = [
        e
        for e in events
        if e.type == EventTypes.INVENTION and e.payload.get("kind") == "discovery"
    ]
    # A "task" is a finished piece of world-building work: a discovery,
    # an invention, a crafting, or a settlement founded.
    tasks = [
        e
        for e in events
        if e.type == EventTypes.CRAFT
        or (
            e.type == EventTypes.INVENTION
            and e.payload.get("kind") in ("discovery", "invention")
        )
        or e.type == EventTypes.SETTLEMENT_FOUNDED
    ]
    messages = [e for e in events if e.type in MESSAGE_EVENTS]

    concepts: set[str] = set()
    for recipe in world.recipes.values():
        if any(
            recipe.name in world.known_recipes(entity) for entity in world.entity_ids
        ):
            concepts.add(f"recipe:{recipe.name}")
    for pattern in world.patterns.values():
        if any(
            pattern.name in world.known_patterns(entity) for entity in world.entity_ids
        ):
            concepts.add(f"pattern:{pattern.name}")
    knowledge = sum(len(agent.knowledge) for agent in agents or [])
    surviving = len(concepts) + knowledge

    ledger = _spend_ledger(world)
    tokens = ledger["tokens"]
    cpu = ledger["cpu_seconds"]
    calls = ledger["model_calls"]
    actions = ledger["actions"]
    compute = tokens + calls + actions + cpu

    return {
        "tokens_per_discovery": _ratio(tokens, len(discoveries)),
        "cpu_seconds_per_solution": _ratio(cpu, len(tasks)),
        "messages_per_successful_task": _ratio(len(messages), len(tasks)),
        "compute_per_surviving_concept": _ratio(compute, surviving),
        "raw": {
            "tokens": tokens,
            "model_calls": calls,
            "cpu_seconds": cpu,
            "actions": actions,
            "compute": compute,
            "discoveries": len(discoveries),
            "tasks": len(tasks),
            "messages": len(messages),
            "surviving_concepts": surviving,
        },
    }


# ----------------------------------------------------------------------
# The campaign's minds
# ----------------------------------------------------------------------


class _Script:
    """A staged script: directives consumed one per tick, one at a time."""

    def __init__(self, script: list[dict]) -> None:
        self.script = script
        self.index = 0

    @property
    def done(self) -> bool:
        return self.index >= len(self.script)

    def decide(self, observation: dict) -> dict:
        if self.done:
            return {"action": {"action": "look"}}
        directive = self.script[self.index]
        self.index += 1
        return {"action": directive}


class CampaignPolicy:
    """The founder's campaign, as a staged script.

    Discover, announce, craft, build, settle â€” the composite task in
    one place. An instrument, not a mind: the scenario knows its own
    grammar. Model mode runs the same campaign through a ModelPolicy.
    """

    def __init__(self, provider=None) -> None:
        if provider is not None:
            from app.simulation.model_policy import ModelPolicy

            self._model = ModelPolicy(provider, system_prompt=CAMPAIGN_SYSTEM_PROMPT)
            # The engine drives the async path by asking the *policy*
            # for ``refresh``; the wrapper must expose it (S33 charges
            # what a model thinks).
            self.refresh = self._model.refresh
            self._script = None
            return
        script: list[dict] = []
        for _ in range(3):  # discover while the wood lasts
            script.append({"action": "discover"})
        script.append({"action": "announce", "scope": "population", "message": "we begin"})
        script.append({"action": "craft", "recipe": "wood_axe"})
        for direction in ("east", "north", "east"):  # raise the home
            script.append(
                {"action": "build", "block": "wood_block", "direction": direction, "purpose": "home"}
            )
        script.append({"action": "settle", "name": "Foundry"})
        self._model = None
        self._script = _Script(script)

    def decide(self, observation: dict) -> dict:
        if self._model is not None:
            return self._model.decide(observation)
        return self._script.decide(observation)


class HeirPolicy:
    """The neighbour: joins, banks, gathers â€” the campaign's upkeep.

    It joins the founder's settlement, deposits what it gathers into
    the shared storehouse, and keeps the grove worked, so the campaign
    has messages, storage and surviving culture, not one busy agent.
    """

    def __init__(self, provider=None) -> None:
        if provider is not None:
            from app.simulation.model_policy import ModelPolicy

            self._model = ModelPolicy(provider, system_prompt=CAMPAIGN_SYSTEM_PROMPT)
            # The engine drives the async path by asking the *policy*
            # for ``refresh``; the wrapper must expose it (S33 charges
            # what a model thinks).
            self.refresh = self._model.refresh
            self._script = None
            return
        script: list[dict] = []
        script.append({"action": "join_settlement", "settlement_id": 1})
        for _ in range(3):
            script.append({"action": "gather", "resource": "wood"})
            script.append({"action": "deposit", "resource": "wood", "amount": 1})
            script.append({"action": "announce", "scope": "population", "message": "restocked"})
        self._model = None
        self._script = _Script(script)

    def decide(self, observation: dict) -> dict:
        if self._model is not None:
            return self._model.decide(observation)
        return self._script.decide(observation)


CAMPAIGN_SYSTEM_PROMPT = (
    "You are an agent in a grid world with trees, taking part in a "
    "campaign. Discover recipes with 'discover', say things to your "
    "population with 'announce', make tools with 'craft', build with "
    "'build', found a settlement with 'settle' naming it, join one "
    "with 'join_settlement', store wood with 'deposit', gather wood "
    "with 'gather'. Decide from the observation each tick. Reply with "
    "JSON only: "
    '{"action": {"action": "discover|announce|craft|build|settle|'
    'join_settlement|deposit|gather|move|look", "scope": "population", '
    '"message": string, "recipe": "wood_axe", "name": string, '
    '"block": "wood_block", "direction": "north|south|east|west", '
    '"resource": "wood", "amount": 1, "settlement_id": 1}, '
    '"goal_update": string|null, "thought_summary": string|null, '
    '"message": string|null} The world validates every action.'
)


# ----------------------------------------------------------------------
# The runner and the study
# ----------------------------------------------------------------------


def run_campaign(
    *,
    session_factory,
    mode: str = "scripted",
    budget: dict | None = None,
    seed: str = "campaign",
    ticks: int = 60,
) -> dict:
    """The composite campaign: discover, announce, craft, build, settle.

    ``budget`` is the run's compute ceiling (kind -> cap); ``None``
    means unconstrained. The scenario is identical either way â€” that
    is what makes runs comparable.
    """
    if mode not in ("scripted", "model"):
        raise ValueError(f"unknown mode {mode!r}; expected scripted or model")

    name = f"campaign-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=RUN_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={"mode": mode, "budget": budget or {}},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    provider = None
    if mode == "model":
        from app.models.config import provider_from_settings

        provider = provider_from_settings(settings)

    bus = EventBus()
    world = World(
        str(seed),
        WORLD_SIZE,
        WORLD_SIZE,
        terrain=[[Terrain.FLOOR] * WORLD_SIZE for _ in range(WORLD_SIZE)],
        event_bus=bus,
    )
    engine = Engine(world, population_id=1)
    if budget:
        world.set_budget(1, **budget)
        world.experiment_budget.limits.update(dict(budget))

    policies = [CampaignPolicy(provider), HeirPolicy(provider)]
    spots = [(3, 3), (7, 3)]
    agents = []
    for index, policy in enumerate(policies, start=1):
        agent = Agent(agent_id=index, policy=policy, observation_radius=3)
        engine.spawn_agent(agent, Position(*spots[index - 1]))
        agents.append(agent)
    for x, y in GROVE:
        world.place_object("tree", Position(x, y), properties={"quantity": 4, "resource": "wood"})
    world.credit_resource(1, "wood", 6)
    world.credit_resource(2, "wood", 2)

    asyncio.run(_drive(engine, ticks))

    measures = measure_efficiency(world, agents)
    record = {
        "experiment_id": experiment_id,
        "name": name,
        "mode": mode,
        "budget": budget or {},
        "measures": measures,
        "tick": world.tick,
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": mode,
            "budget": budget or {},
            "measures": measures,
        }
        session.commit()
    return record


async def _drive(engine: Engine, ticks: int) -> None:
    """Drive a campaign, stepping the async path (model-ready)."""
    for _tick in range(1, ticks + 1):
        await engine.step_async()


def run_efficiency_study(
    *,
    session_factory,
    budgets: list[dict] | None = None,
    mode: str = "scripted",
    seed: str = "efficiency",
    ticks: int = 60,
    export_path: str | None = None,
) -> dict:
    """Identical scenarios under different compute budgets, compared."""
    if budgets is None:
        budgets = [
            {"label": "unconstrained"},
            {"label": "tight", "model_calls": 2, "actions": 12},
        ]
    labels = [entry.get("label") for entry in budgets]
    if any(label is None for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("every budget needs a distinct label")

    name = f"study-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=STUDY_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={"mode": mode, "budgets": budgets, "ratios": list(RATIOS)},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    runs = []
    for index, entry in enumerate(budgets):
        caps = {kind: value for kind, value in entry.items() if kind != "label"}
        record = run_campaign(
            session_factory=session_factory,
            mode=mode,
            budget=caps or None,
            seed=f"{seed}-{index}",
            ticks=ticks,
        )
        runs.append(
            {
                "label": entry["label"],
                "budget": caps,
                "experiment_id": record["experiment_id"],
                "measures": record["measures"],
            }
        )

    comparison = {
        "ratios": {
            ratio: {
                "per_run": {run["label"]: run["measures"][ratio] for run in runs},
                "values": [
                    value
                    for value in (run["measures"][ratio] for run in runs)
                    if value is not None
                ],
            }
            for ratio in RATIOS
        },
        "accomplished": {
            run["label"]: {
                "discoveries": run["measures"]["raw"]["discoveries"],
                "tasks": run["measures"]["raw"]["tasks"],
                "messages": run["measures"]["raw"]["messages"],
                "surviving_concepts": run["measures"]["raw"]["surviving_concepts"],
            }
            for run in runs
        },
    }
    for table in comparison["ratios"].values():
        values = table["values"]
        table["mean"] = round(stats.fmean(values), 6) if values else None
        table["min"] = min(values) if values else None
        table["max"] = max(values) if values else None
        table["n"] = len(values)

    study = {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": STUDY_SCENARIO,
        "mode": mode,
        "seed": seed,
        "budgets": budgets,
        "runs": runs,
        "comparison": comparison,
        "ratios": list(RATIOS),
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": mode,
            "budgets": budgets,
            "ratios": list(RATIOS),
            "comparison": comparison,
            "run_experiment_ids": [run["experiment_id"] for run in runs],
        }
        session.commit()
    if export_path:
        study["export_path"] = export_study(study, export_path)
    return study


def export_study(study: dict, path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(study, indent=2), encoding="utf-8")
    return str(target)


def print_summary(study: dict) -> None:
    print(
        f"efficiency study {study['name']!r}: {len(study['runs'])} budgets, "
        f"mode {study['mode']}"
    )
    for run in study["runs"]:
        raw = run["measures"]["raw"]
        print(
            f"  {run['label']}: {raw['discoveries']} discoveries, {raw['tasks']} tasks, "
            f"{raw['messages']} messages, {raw['surviving_concepts']} concepts "
            f"for {raw['compute']} compute"
        )
    for ratio in RATIOS:
        table = study["comparison"]["ratios"][ratio]
        rendered = ", ".join(
            f"{label} {value if value is not None else 'â€”'}"
            for label, value in table["per_run"].items()
        )
        print(f"  {ratio}: {rendered}")


def _parse_budgets(text: str | None) -> list[dict] | None:
    """Parse "label:kind=cap,...;label:..." into the study's budget list."""
    if not text:
        return None
    budgets = []
    for chunk in text.split(";"):
        label, _, caps = chunk.partition(":")
        entry: dict = {"label": label.strip()}
        for pair in caps.split(","):
            if not pair.strip():
                continue
            kind, _, value = pair.partition("=")
            entry[kind.strip()] = float(value)
        budgets.append(entry)
    return budgets


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.efficiency",
        description="Measure compute efficiency under different budgets (roadmap S34).",
    )
    parser.add_argument("--mode", default="scripted", choices=["scripted", "model"])
    parser.add_argument("--seed", default="efficiency")
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument(
        "--budgets",
        default=None,
        help='semicolon-separated runs: "label:kind=cap,..." â€” e.g. '
             '"unconstrained;tight:model_calls=2,actions=12"',
    )
    parser.add_argument("--export", default=None)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    study = run_efficiency_study(
        session_factory=SessionLocal,
        budgets=_parse_budgets(args.budgets),
        mode=args.mode,
        seed=args.seed,
        ticks=args.ticks,
        export_path=args.export,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
