"""The 100-generation lineage experiment (guide §11 / roadmap S11).

The first serious Flood experiment: a founder receives a controlled
knowledge set (10 facts), creates Agent 1; every child decides what to
pass onward; repeat to generation 100 — then measure information drift.

What this module is:

- a **runner** (`run_lineage_experiment`) that drives the chain through
  the S09/S10 mechanisms (``Engine.create_child`` + the inheritance
  package), recording every generation on the world timeline and the
  agents table, with an ``ExperimentModel`` row describing the run;
- **scripted calibrations** (full retention, lossy, altering, negating,
  new-fact policies) that produce *known* transmission phenomena, so
  the metrics can be checked against ground truth;
- **metrics** (roadmap S11): retained / lost / altered / new facts,
  contradictions (guide §11), message lengths, and a deterministic
  semantic-similarity proxy (token Jaccard — an embedding provider is a
  later sprint's luxury);
- **replay** (`replay_lineage_experiment`): the lineage rebuilt from
  persisted events alone — replay never re-calls a model (guide
  §"replay");
- **export**: the report as JSON.

The experiment is deterministic for every scripted mode; ``mode="model"``
runs the same chain with a real ``ModelPolicy``, where each generation's
transmission is a genuine model decision.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
from datetime import datetime, timezone

from app.config.settings import settings
from app.models.config import model_configuration, provider_from_settings
from app.persistence.models import (
    AgentModel,
    ExperimentModel,
    PopulationModel,
    WorldModel,
)
from app.persistence.repositories import (
    AgentRecorder,
    CheckpointRepository,
    DatabaseEventRecorder,
)
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

DEFAULT_GENERATIONS = 100
DEFAULT_FACTS: tuple[str, ...] = (
    "the void is dark",
    "water blocks the walker",
    "walls stop movement",
    "food restores strength",
    "the seed fixes the world",
    "stones are heavy",
    "trees stay in place",
    "every action is recorded",
    "the observer tells truth",
    "parents pass what they remember",
)
WORLD_SIZE = 20  # floor for the auto-sized world; the default run fits in it
ALTER_THRESHOLD = 0.3  # Jaccard at/above which a non-exact fact counts as altered
NEGATION_TOKENS = {"not", "never", "no", "none", "cannot"}


# ----------------------------------------------------------------------
# Scripted calibrations: policies that transmit *known* phenomena
# ----------------------------------------------------------------------


class _ExperimentPolicy:
    """A scripted mind whose decision declares an inheritance package.

    The package is built from the agent's own observation — which, since
    S10, includes the knowledge this agent received at birth (guide §11:
    the child decides what to pass onward). ``_calls`` counts this
    policy's decisions, which is the generation counter of the chain.
    """

    def __init__(self) -> None:
        self._calls = 0

    def decide(self, observation: dict) -> dict:
        self._calls += 1
        knowledge = list(observation.get("knowledge", []))
        self._transform(knowledge)
        return {
            "action": {"action": "look"},
            "inheritance": {
                "traits": {},
                "knowledge": knowledge,
                "message": f"generation {self._calls}: "
                f"{len(knowledge)} facts carried forward",
                "cultural_artifacts": [],
            },
        }

    def _transform(self, knowledge: list) -> None:
        """Mutate the outgoing knowledge (subclasses introduce drift)."""


class FullRetentionPolicy(_ExperimentPolicy):
    """The control: everything passes, verbatim, forever."""


class LossyRetentionPolicy(_ExperimentPolicy):
    """Drops the next fact every 10th decision (a measurable staircase)."""

    def _transform(self, knowledge: list) -> None:
        if self._calls % 10 == 0 and knowledge:
            knowledge.pop((self._calls // 10 - 1) % len(knowledge))


class AlteringPolicy(_ExperimentPolicy):
    """Re-words the next fact every 10th decision: same content, altered form."""

    def _transform(self, knowledge: list) -> None:
        if self._calls % 10 == 0 and knowledge:
            index = (self._calls // 10 - 1) % len(knowledge)
            knowledge[index] = f"it is said that {knowledge[index]}"


class NegatingPolicy(_ExperimentPolicy):
    """Negates the next fact every 10th decision: a contradiction."""

    def _transform(self, knowledge: list) -> None:
        if self._calls % 10 == 0 and knowledge:
            index = (self._calls // 10 - 1) % len(knowledge)
            words = knowledge[index].split()
            if words and not NEGATION_TOKENS & {w.lower() for w in words}:
                knowledge[index] = " ".join(words[:-1] + ["not"] + [words[-1]])


class NewFactsPolicy(_ExperimentPolicy):
    """Adds a fresh fact every 10th decision: drift in the other direction."""

    def _transform(self, knowledge: list) -> None:
        if self._calls % 10 == 0:
            knowledge.append(f"the echo remembers generation {self._calls}")


_MODES = {
    "full": FullRetentionPolicy,
    "lossy": LossyRetentionPolicy,
    "altering": AlteringPolicy,
    "negating": NegatingPolicy,
    "new": NewFactsPolicy,
    "model": None,  # built from settings — see _build_policy
}


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------


def tokens(text: str) -> set[str]:
    """Word tokens of a fact — the shared unit of the drift metrics.

    Public because the S15 lineage explorer measures drift with the
    same rules the experiment does.
    """
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _classify_fact(fact: str, originals: list[str], original_tokens: list[set]) -> str:
    """Where one transmitted fact sits relative to the original set.

    ``retained`` (verbatim), ``contradicted`` (an original's tokens plus a
    negation — the documented heuristic), ``altered`` (similar wording,
    changed content) or ``new`` (no original close enough). Similarity is
    best-match token Jaccard.
    """
    if fact in originals:
        return "retained"
    fact_tokens = tokens(fact)
    for original, tokens_ in zip(originals, original_tokens):
        if tokens_ < fact_tokens and (fact_tokens - tokens_) & NEGATION_TOKENS:
            return "contradicted"
    best = max((_jaccard(fact_tokens, tokens_) for tokens_ in original_tokens), default=0.0)
    if best >= ALTER_THRESHOLD:
        return "altered"
    return "new"


def generation_metrics(
    generation: int,
    knowledge: list[str],
    message: str | None,
    originals: list[str],
    original_tokens: list[set],
) -> dict:
    """One row of the roadmap's measure list for one generation."""
    classified: dict[str, list[str]] = {"retained": [], "altered": [], "contradicted": [], "new": []}
    similarities = []
    for fact in knowledge:
        classified[_classify_fact(fact, originals, original_tokens)].append(fact)
        similarities.append(
            max((_jaccard(tokens(fact), tokens_) for tokens_ in original_tokens), default=0.0)
        )
    received = set(knowledge)
    return {
        "generation": generation,
        "facts_received": len(knowledge),
        "retained": sorted(classified["retained"]),
        "altered": sorted(classified["altered"]),
        "contradicted": sorted(classified["contradicted"]),
        "new": sorted(classified["new"]),
        "lost": sorted(fact for fact in originals if fact not in received),
        "message": message,
        "message_length": len(message) if message else 0,
        "avg_similarity": round(statistics.fmean(similarities), 4) if similarities else 0.0,
    }


def _report(
    *,
    experiment_id: int,
    name: str,
    scenario: str,
    seed: str,
    mode: str,
    originals: list[str],
    trajectory: list[dict],
) -> dict:
    final = trajectory[-1] if trajectory else {}
    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": scenario,
        "seed": seed,
        "mode": mode,
        "generations": len(trajectory),
        "originals": originals,
        "trajectory": trajectory,
        "final": final,
        "totals": {
            "retained_facts": len(final.get("retained", [])),
            "lost_facts": len(final.get("lost", [])),
            "altered_facts": len(final.get("altered", [])) + len(final.get("contradicted", [])),
            "contradicted_facts": len(final.get("contradicted", [])),
            "new_facts": len(final.get("new", [])),
            "avg_message_length": round(
                statistics.fmean([t["message_length"] for t in trajectory]), 2
            )
            if trajectory
            else 0.0,
            "final_avg_similarity": final.get("avg_similarity", 0.0),
        },
    }


# ----------------------------------------------------------------------
# The runner
# ----------------------------------------------------------------------


def _build_policy(mode: str):
    """(policy, configuration fragment) for a mode. Model mode reads settings."""
    if mode == "model":
        return ModelPolicy(provider_from_settings(settings)), {"policy": "ModelPolicy", **model_configuration()}
    policy_class = _MODES.get(mode)
    if policy_class is None:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(_MODES)}")
    return policy_class(), {"policy": policy_class.__name__}


async def _intent(policy, parent: Agent) -> dict | None:
    """The inheritance package the experiment's mind intends to pass.

    Model policies are *refreshed* (awaited); scripted ones just decide.
    Either way the decision is made against the *parent's* observation —
    which includes the knowledge that parent received at birth (guide
    §11: the child decides what to pass onward, from what it was given).

    One mind drives the whole chain: the agents in the lineage are
    genetic carriers, while this policy is the experiment's decision
    instrument, so its per-decision counters (calibration staircases)
    advance once per generation, not once per agent.
    """
    observation = parent.observe()
    refresh = getattr(policy, "refresh", None)
    if refresh is not None:
        decision = await refresh(observation) or {}
    else:
        decision = policy.decide(observation)
    if not isinstance(decision, dict):
        return None
    intent = decision.get("inheritance")
    return intent if isinstance(intent, dict) else None


def _auto_world_size(generations: int) -> int:
    """A square flat world whose interior holds the whole chain.

    The chain is placed row-major (``_chain_position``), so the interior
    needs ``generations + 1`` cells: W - 2 >= sqrt(generations + 1).
    Sizing is explicit rather than relying on the engine's adjacency
    walk, which can trap itself against its own path well below full
    density.
    """
    needed = math.isqrt(generations + 1) + 1  # interior side length
    return max(WORLD_SIZE, needed + 2)


def _chain_position(generation: int, world_size: int) -> Position:
    """The chain's cell for a generation: row-major, one cell each.

    The founder (generation 0) sits at (1,1); each child claims the
    next interior cell. Placement is a pure function of the generation
    number, so a resumed chain lands exactly where it would have —
    distinct cells by construction, no walk, no trap.
    """
    row_length = max(1, world_size - 2)
    return Position(1 + generation % row_length, 1 + generation // row_length)


def run_lineage_experiment(
    *,
    session_factory,
    mode: str = "full",
    generations: int = DEFAULT_GENERATIONS,
    facts: list[str] | None = None,
    seed: str = "lineage",
    name: str | None = None,
    world_size: int | None = None,
    checkpoint_every: int | None = None,
    event_retention: int | None = None,
    batch_size: int = 500,
) -> dict:
    """Run the lineage experiment end to end; returns the report.

    Synchronous by design (it drives the async model path internally):
    a CLI or test calls one function. ``mode`` selects the minds —
    scripted calibrations or a live ``ModelPolicy``.

    Scale switches (S12): ``world_size`` defaults to an auto-sized flat
    world that fits the chain; ``checkpoint_every`` writes resumable
    checkpoints every N generations; ``event_retention`` caps the
    world's in-memory event window (the database remains the durable
    record); ``batch_size`` commits the event log in batches (the scale
    that makes 10,000 generations take seconds, not minutes).
    """
    originals = list(facts if facts is not None else DEFAULT_FACTS)
    original_tokens = [tokens(fact) for fact in originals]
    policy, configuration = _build_policy(mode)
    name = name or f"lineage-{seed}"
    world_size = _auto_world_size(generations) if world_size is None else world_size

    with session_factory() as session:
        world_row = WorldModel(name=f"world-{name}", seed=str(seed))
        session.add(world_row)
        session.commit()
        world_id = world_row.id
        population = PopulationModel(name=f"population-{world_id}", world_id=world_id)
        session.add(population)
        session.commit()
        population_id = population.id

        experiment = ExperimentModel(
            name=name,
            world_id=world_id,
            scenario="lineage_100gen",
            seed=str(seed),
            status="running",
            model_configuration={
                "mode": mode,
                **configuration,
                "facts": originals,
            },
            compute_budget={"max_model_calls": generations if mode == "model" else 0},
            generation_limit=generations,
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    bus = EventBus()
    event_recorder = DatabaseEventRecorder(
        session_factory, world_id, batch_size=batch_size
    )
    bus.subscribe(event_recorder)
    world = World(
        str(seed),
        world_size,
        world_size,
        terrain=[[Terrain.FLOOR] * world_size for _ in range(world_size)],
        event_bus=bus,
        event_retention=event_retention,
    )
    engine = Engine(world, population_id=population_id)

    # The lineage's agents are carriers with the default scripted mind —
    # they never act in this experiment. `policy` is the experiment's
    # decision instrument: one mind, refreshed/decided once per
    # generation against the current parent's observation.
    founder = Agent(agent_id=1, policy=WanderPolicy(), knowledge=list(originals))
    engine.spawn_agent(founder, _chain_position(0, world_size))

    local_to_global: dict[int, int] = {}
    with session_factory() as session:
        record = AgentModel(
            world_id=world_id,
            local_id=founder.agent_id,
            population_id=population_id,
            generation=founder.generation,
            birth_tick=0,
            status="active",
            location=founder.position.to_dict() if founder.position else None,
            inherited_traits={},
            inherited_knowledge=[],
            cultural_artifacts=[],
            acquired_knowledge=list(originals),  # the controlled set is *given*
        )
        session.add(record)
        session.flush()
        local_to_global[founder.agent_id] = record.id
        session.commit()
    agent_recorder = AgentRecorder(
        session_factory, world_id, population_id, local_to_global
    )
    bus.subscribe(agent_recorder)

    checkpoints = CheckpointRepository(session_factory)

    def _checkpoint(agent: Agent) -> None:
        if checkpoint_every is None:
            return
        checkpoints.save(
            experiment_id,
            agent.generation,
            {
                "parent_local_id": agent.agent_id,
                "position": agent.position.to_dict() if agent.position else None,
                "generation": agent.generation,
                "knowledge": list(agent.knowledge),
                "goal": agent.goal,
                "traits": agent.traits,
                "cultural_artifacts": list(agent.cultural_artifacts),
                "policy_calls": getattr(policy, "_calls", None),
                "world_size": world_size,
                "event_retention": event_retention,
            },
        )

    async def _drive() -> list[dict]:
        trajectory: list[dict] = []
        parent = founder
        for generation in range(1, generations + 1):
            intent = await _intent(policy, parent)
            child = engine.create_child(
                parent.agent_id,
                inheritance=intent,
                position=_chain_position(generation, world_size),
            )
            trajectory.append(
                generation_metrics(
                    generation,
                    child.knowledge,
                    (intent or {}).get("message"),
                    originals,
                    original_tokens,
                )
            )
            if checkpoint_every is not None and (
                generation % checkpoint_every == 0 or generation == generations
            ):
                _checkpoint(child)
            parent = child
        return trajectory

    trajectory = asyncio.run(_drive())
    event_recorder.flush()

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        session.commit()

    return _report(
        experiment_id=experiment_id,
        name=name,
        scenario="lineage_100gen",
        seed=str(seed),
        mode=mode,
        originals=originals,
        trajectory=trajectory,
    )


# ----------------------------------------------------------------------
# Replay and export
# ----------------------------------------------------------------------


def resume_lineage_experiment(
    session_factory,
    experiment_id: int,
    *,
    generations: int,
    world_size: int | None = None,
    checkpoint_every: int | None = None,
    event_retention: int | None = None,
    batch_size: int = 500,
) -> dict:
    """Continue a checkpointed run from its chain head (S12).

    Resume needs no serialized world: the durable rows are the state.
    The chain head (highest-generation agent row) is restored as the
    current parent — its lineage link, carried inheritance and location
    all live on its row — and the recorder's local → global map is
    rebuilt from those same rows, so new children link to their real
    parents: no orphaned lineage records, no duplicate ids. The
    experiment mind's counter continues from the generation count (one
    decision per generation), so calibration staircases continue rather
    than restart.

    Interrupted *and* completed runs both resume — the latter is how a
    pilot run is extended ("run it to 10,000"). The world is rebuilt
    fresh, sized to fit the *target* generation count.
    """
    with session_factory() as session:
        experiment = session.get(ExperimentModel, experiment_id)
        if experiment is None:
            raise ValueError(f"unknown experiment {experiment_id!r}")
        configuration = dict(experiment.model_configuration or {})
        world_id = experiment.world_id
        name = experiment.name
        seed = experiment.seed
        originals = list(configuration.get("facts") or DEFAULT_FACTS)
        mode = configuration.get("mode", "full")

        population = session.query(PopulationModel).filter_by(world_id=world_id).first()
        population_id = population.id if population else None
        rows = list(
            session.query(AgentModel)
            .filter_by(world_id=world_id)
            .order_by(AgentModel.id)
        )

    checkpoint = CheckpointRepository(session_factory).latest(experiment_id)
    if checkpoint is None:
        raise ValueError(f"experiment {experiment_id} has no checkpoint to resume from")
    state = dict(checkpoint.state or {})

    # The chain head is the highest-generation agent row — for an
    # interrupted run the latest checkpoint sits at or behind it. The
    # row carries everything the parent needs to continue: its local id
    # and lineage link, its carried inheritance (knowledge, goal,
    # traits, artifacts — exactly the package the recorder persisted at
    # its birth), and its location. Resuming from the row, not the
    # checkpoint, is what keeps a resumed chain free of duplicate or
    # orphaned rows.
    head = max(rows, key=lambda r: (r.generation, r.local_id or 0))
    start_generation = head.generation
    if generations <= start_generation:
        raise ValueError(
            f"experiment {experiment_id} is already at generation {start_generation}; "
            f"--generations must be greater"
        )

    rows_by_global = {row.id: row for row in rows}
    founder_knowledge = (
        list(head.acquired_knowledge or []) if head.generation == 0 else list(head.inherited_knowledge or [])
    )

    policy, _ = _build_policy(mode)
    # Each generation costs exactly one policy decision, so the mind's
    # counter is the generation count — calibration staircases continue
    # rather than restart (the checkpoint records it too, but the row
    # is always at least as current).
    if hasattr(policy, "_calls"):
        policy._calls = start_generation

    world_size = max(
        world_size or 0,
        state.get("world_size") or 0,
        _auto_world_size(generations),
    )
    event_retention = (
        event_retention if event_retention is not None else state.get("event_retention")
    )

    bus = EventBus()
    event_recorder = DatabaseEventRecorder(
        session_factory, world_id, batch_size=batch_size
    )
    bus.subscribe(event_recorder)
    world = World(
        str(seed),
        world_size,
        world_size,
        terrain=[[Terrain.FLOOR] * world_size for _ in range(world_size)],
        event_bus=bus,
        event_retention=event_retention,
    )
    engine = Engine(world, population_id=population_id)

    parent = Agent(
        agent_id=head.local_id,
        policy=WanderPolicy(),
        parent_id=(
            rows_by_global[head.parent_id].local_id
            if head.parent_id in rows_by_global
            else None
        ),
        generation=head.generation,
        population_id=population_id,
        knowledge=founder_knowledge,
        goal=(head.goals or {}).get("goal") if head.goals else None,
        traits=dict(head.inherited_traits or {}),
        cultural_artifacts=list(head.cultural_artifacts or []),
    )
    # The head is re-placed at its generation's cell in the (possibly
    # larger) resumed world: every cell is then a function of the
    # generation number, and collisions are impossible by construction.
    engine.spawn_agent(parent, _chain_position(head.generation, world_size))

    # The recorder's map is rebuilt from the durable rows, so the next
    # birth links its parent's *existing* row rather than a fresh one.
    local_to_global = {row.local_id: row.id for row in rows if row.local_id is not None}
    agent_recorder = AgentRecorder(
        session_factory, world_id, population_id, local_to_global
    )
    bus.subscribe(agent_recorder)

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "running"
        experiment_row.started_at = experiment_row.started_at or datetime.now(timezone.utc)
        session.commit()

    original_tokens = [tokens(fact) for fact in originals]
    checkpoints = CheckpointRepository(session_factory)

    async def _drive() -> list[dict]:
        trajectory: list[dict] = []
        current = parent
        for generation in range(start_generation + 1, generations + 1):
            intent = await _intent(policy, current)
            child = engine.create_child(
                current.agent_id,
                inheritance=intent,
                position=_chain_position(generation, world_size),
            )
            trajectory.append(
                generation_metrics(
                    generation,
                    child.knowledge,
                    (intent or {}).get("message"),
                    originals,
                    original_tokens,
                )
            )
            if checkpoint_every is not None and (
                generation % checkpoint_every == 0 or generation == generations
            ):
                checkpoints.save(
                    experiment_id,
                    generation,
                    {
                        "parent_local_id": child.agent_id,
                        "position": child.position.to_dict() if child.position else None,
                        "generation": child.generation,
                        "knowledge": list(child.knowledge),
                        "goal": child.goal,
                        "traits": child.traits,
                        "cultural_artifacts": list(child.cultural_artifacts),
                        "policy_calls": getattr(policy, "_calls", None),
                        "world_size": world_size,
                        "event_retention": event_retention,
                    },
                )
            current = child
        return trajectory

    trajectory = asyncio.run(_drive())
    event_recorder.flush()

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        session.commit()

    return _report(
        experiment_id=experiment_id,
        name=name,
        scenario="lineage_100gen",
        seed=str(seed),
        mode=mode,
        originals=originals,
        trajectory=trajectory,
    )


def replay_lineage_experiment(session_factory, experiment_id: int) -> dict:
    """Rebuild the lineage from persisted events alone (guide §"replay").

    Reads the experiment row and the world's AGENT_BORN timeline — no
    engine, no model calls. The rebuilt chain is the experiment's
    durable form: every generation, what it received, and what it was
    told.
    """
    with session_factory() as session:
        experiment = session.get(ExperimentModel, experiment_id)
        if experiment is None:
            raise ValueError(f"unknown experiment {experiment_id!r}")
        configuration = dict(experiment.model_configuration or {})
        world_id = experiment.world_id
        scenario = experiment.scenario
        name = experiment.name
        seed = experiment.seed

    with session_factory() as session:
        from sqlalchemy import select

        from app.persistence.models import EventModel

        rows = list(
            session.scalars(
                select(EventModel)
                .where(
                    EventModel.world_id == world_id,
                    EventModel.type == EventTypes.AGENT_BORN,
                )
                .order_by(EventModel.id)
            )
        )

    generations = [
        {
            "generation": row.payload["generation"],
            "parent_local_id": row.payload["parent_id"],
            "child_local_id": row.payload["child_id"],
            "tick": row.tick,
            "inheritance": row.payload["inheritance"],
        }
        for row in rows
    ]
    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": scenario,
        "seed": seed,
        "mode": configuration.get("mode"),
        "originals": configuration.get("facts", []),
        "generations": generations,
        "chain_length": len(generations),
    }


def export_report(report: dict, path: str) -> str:
    """Write the report as JSON; returns the path written."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def print_summary(report: dict) -> None:
    """Human-readable digest, for the CLI."""
    totals = report["totals"]
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['mode']} mode)")
    print(f"  generations : {report['generations']}")
    print(f"  retained    : {totals['retained_facts']}/{len(report['originals'])}")
    print(f"  lost        : {totals['lost_facts']}")
    print(f"  altered     : {totals['altered_facts']} (contradicted: {totals['contradicted_facts']})")
    print(f"  new         : {totals['new_facts']}")
    print(f"  msg length  : avg {totals['avg_message_length']}")
    print(f"  similarity  : {totals['final_avg_similarity']}")
