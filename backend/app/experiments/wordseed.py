"""The word-seed experiment (guide §12 / roadmap S16).

Agents receive seed words and produce three associated concepts, then
create one cultural artifact — story, theory, rule, invention, game,
poem, building concept — stored as a cultural object in the world.
The verification runs *multiple populations from identical seeds* and
compares outputs: the scripted control produces identical artifacts
(divergence zero, proving storage and comparison), a scatter
calibration diverges deterministically, and the live model mode is
where identical seeds are expected to genuinely diverge.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

from app.config.settings import settings
from app.models.config import model_configuration, provider_from_settings
from app.models.decision import DecisionError, extract_json_object
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
from app.simulation.world import Position, Terrain, World

DEFAULT_SEEDS: tuple[str, ...] = ("light", "water", "stone", "echo", "void")
ARTIFACT_KINDS: tuple[str, ...] = (
    "story",
    "theory",
    "rule",
    "invention",
    "game",
    "poem",
    "building concept",
)
LEXICON: tuple[str, ...] = (
    "light", "dark", "water", "stone", "tree", "echo",
    "void", "seed", "root", "ash", "rain", "door",
)

WORD_SEED_SYSTEM_PROMPT = (
    "You are an agent inside a small grid world, given one seed word. "
    "Reply with JSON only, in this shape: "
    '{"concepts": ["word", "word", "word"], '
    '"artifact": {"kind": "story|theory|rule|invention|game|poem|building concept", '
    '"title": "short title", "body": "one or two sentences"}}. '
    "The three concepts are what the seed word makes you think of; the "
    "artifact is one cultural object you create from them."
)


# ----------------------------------------------------------------------
# Scripted calibrations: deterministic concept/artifact derivation
# ----------------------------------------------------------------------


def _scripted_artifact(seed_word: str, population_index: int, mode: str) -> dict:
    """Derive concepts + artifact from a seed word (guide §12's shape).

    ``scripted`` is the control — a pure function of the seed word, so
    identically-seeded populations agree exactly. ``scatter`` salts the
    derivation with the population index: deterministic, but different
    per population, which is what exercises the comparison math without
    a model.
    """
    salt = "" if mode == "scripted" else f":{population_index}"
    digest = hashlib.sha256(f"{seed_word}{salt}".encode()).hexdigest()

    concepts = [
        LEXICON[(int(digest[2 * i : 2 * i + 2], 16) + i) % len(LEXICON)] for i in range(3)
    ]
    kind = ARTIFACT_KINDS[int(digest[:2], 16) % len(ARTIFACT_KINDS)]
    return {
        "concepts": concepts,
        "kind": kind,
        "title": f"the {concepts[0]} {seed_word}",
        "body": f"a {kind} of {concepts[0]}, {concepts[1]} and {concepts[2]}",
    }


async def _model_artifact(provider, seed_word: str) -> dict:
    """Ask a live model for concepts + artifact; invalid output fails loudly."""
    request = ModelRequest(
        observation={"seed_word": seed_word},
        system_prompt=WORD_SEED_SYSTEM_PROMPT,
    )
    response: ModelResponse = await provider.generate(request)
    try:
        data = extract_json_object(response.text)
    except DecisionError as exc:
        raise ValueError(f"model output for {seed_word!r} is not usable: {exc}") from exc

    concepts = data.get("concepts")
    artifact = data.get("artifact")
    if not isinstance(concepts, list) or not concepts or not all(
        isinstance(c, str) for c in concepts
    ):
        raise ValueError(f"model concepts for {seed_word!r} are not a word list: {concepts!r}")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("kind"), str):
        raise ValueError(f"model artifact for {seed_word!r} is malformed: {artifact!r}")
    return {
        "concepts": [str(c) for c in concepts],
        "kind": str(artifact["kind"]),
        "title": str(artifact.get("title") or "untitled"),
        "body": str(artifact.get("body") or ""),
    }


def _world_size(agent_count: int) -> int:
    needed = 3
    while (needed - 2) * (needed - 2) < agent_count:
        needed += 1
    return max(20, needed)


def _agent_position(index: int, world_size: int) -> Position:
    row_length = max(1, world_size - 2)
    return Position(1 + index % row_length, 1 + index // row_length)


# ----------------------------------------------------------------------
# Comparison across identically-seeded populations
# ----------------------------------------------------------------------


def _compare(population_artifacts: list[dict], seeds: list[str]) -> dict:
    """Compare outputs of populations that received identical seeds."""
    by_seed: dict[str, list[dict]] = {seed: [] for seed in seeds}
    for population in population_artifacts:
        for artifact in population["artifacts"]:
            by_seed.setdefault(artifact["seed"], []).append(artifact)

    per_seed = {}
    identical_seeds, divergent_seeds = [], []
    for seed, variants in by_seed.items():
        fingerprints = {
            (tuple(v["concepts"]), v["kind"], v["title"], v["body"]) for v in variants
        }
        concept_sets = [set(v["concepts"]) for v in variants]
        union = set().union(*concept_sets) if concept_sets else set()
        intersection = set.intersection(*concept_sets) if concept_sets else set()
        jaccard = len(intersection) / len(union) if union else 1.0
        identical = len(fingerprints) == 1
        (identical_seeds if identical else divergent_seeds).append(seed)
        per_seed[seed] = {
            "variants": len(fingerprints),
            "kinds": sorted({v["kind"] for v in variants}),
            "concept_jaccard": round(jaccard, 4),
            "identical": identical,
        }

    all_artifacts = [a for p in population_artifacts for a in p["artifacts"]]
    return {
        "artifacts_total": len(all_artifacts),
        "unique_artifacts": len(
            {(a["title"], a["body"], tuple(a["concepts"])) for a in all_artifacts}
        ),
        "identical_seeds": sorted(identical_seeds),
        "divergent_seeds": sorted(divergent_seeds),
        "per_seed": per_seed,
    }


# ----------------------------------------------------------------------
# The runner
# ----------------------------------------------------------------------


def run_word_seed_experiment(
    *,
    session_factory,
    mode: str = "scripted",
    seeds: list[str] | None = None,
    populations: int = 2,
    seed: str = "wordseed",
    name: str | None = None,
) -> dict:
    """Run the word-seed experiment; returns the comparison report.

    ``mode``: ``scripted`` (control — a pure function of the seed word),
    ``scatter`` (deterministic per population), or ``model`` (a live
    ModelProvider through the same request/response seam).
    """
    if mode not in ("scripted", "scatter", "model"):
        raise ValueError(f"unknown mode {mode!r}; expected scripted, scatter or model")
    if populations < 1:
        raise ValueError(f"populations must be >= 1, got {populations}")
    seeds = list(seeds if seeds is not None else DEFAULT_SEEDS)
    name = name or f"wordseed-{seed}"
    provider = provider_from_settings(settings) if mode == "model" else None

    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="word_seed",
            seed=str(seed),
            status="running",
            model_configuration={
                "mode": mode,
                "seeds": seeds,
                "populations": populations,
                **(model_configuration() if mode == "model" else {}),
            },
            compute_budget={"max_model_calls": len(seeds) * populations if mode == "model" else 0},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    world_size = _world_size(len(seeds))

    async def _run_all_populations() -> list[dict]:
        # One event loop for the whole run: the provider's AsyncClient
        # is long-lived, and per-call asyncio.run would strand it on a
        # closed loop.
        results = []
        for population_index in range(populations):
            results.append(await _run_population(population_index))
        return results

    async def _run_population(population_index: int) -> dict:
        with session_factory() as session:
            world_row = WorldModel(name=f"world-{name}-{population_index}", seed=str(seed))
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
        world = World(
            str(seed),
            world_size,
            world_size,
            terrain=[[Terrain.FLOOR] * world_size for _ in range(world_size)],
            event_bus=bus,
        )
        engine = Engine(world, population_id=population_id)

        artifacts = []
        for index, seed_word in enumerate(seeds):
            agent = Agent(
                agent_id=index + 1,
                policy=_NoopPolicy(),
                population_id=population_id,
            )
            engine.spawn_agent(agent, _agent_position(index, world_size))

            if provider is not None:
                derived = await _model_artifact(provider, seed_word)
            else:
                derived = _scripted_artifact(seed_word, population_index, mode)

            artifact = {
                "agent_id": agent.agent_id,
                "seed": seed_word,
                "concepts": list(derived["concepts"]),
                "kind": derived["kind"],
                "title": derived["title"],
                "body": derived["body"],
            }
            # Store the artifact as a cultural object: a world object at
            # the agent's cell, a timeline event, and the agent's row.
            world.place_object(
                derived["kind"],
                agent.position,
                properties={
                    "artifact": artifact,
                    "created_by_agent_id": agent.agent_id,
                    "population_id": population_id,
                },
                created_by_agent_id=agent.agent_id,
            )
            world._add_event(
                EventTypes.ARTIFACT_CREATED,
                actor_id=agent.agent_id,
                payload={"seed": seed_word, "artifact": artifact},
            )
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
                        cultural_artifacts=[artifact],
                        acquired_knowledge=list(derived["concepts"]),
                    )
                )
                session.commit()
            artifacts.append(artifact)

        event_recorder.flush()
        return {
            "world_id": world_id,
            "population_id": population_id,
            "artifacts": artifacts,
        }

    population_artifacts = asyncio.run(_run_all_populations())

    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        session.commit()

    return {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": "word_seed",
        "mode": mode,
        "seeds": seeds,
        "populations": populations,
        "population_artifacts": population_artifacts,
        "comparison": _compare(population_artifacts, seeds),
    }


class _NoopPolicy:
    """A carrier mind: word-seed agents are producers, not deciders."""

    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "look"}}


def print_summary(report: dict) -> None:
    comparison = report["comparison"]
    print(f"experiment {report['experiment_id']}: {report['name']} ({report['mode']} mode)")
    print(f"  populations: {report['populations']} · seeds: {len(report['seeds'])}")
    print(f"  artifacts  : {comparison['artifacts_total']} "
          f"({comparison['unique_artifacts']} unique)")
    print(f"  identical seeds across populations: {len(comparison['identical_seeds'])}")
    print(f"  divergent seeds                  : {len(comparison['divergent_seeds'])}")
    for seed_word, stats in comparison["per_seed"].items():
        print(
            f"    {seed_word}: {stats['variants']} variant(s), kinds {stats['kinds']}, "
            f"concept jaccard {stats['concept_jaccard']}"
        )


def export_report(report: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def main() -> None:
    """CLI: ``python -m app.experiments.wordseed [--mode ...]``."""
    import argparse

    from app.persistence.database import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.wordseed",
        description="Run the word-seed experiment (guide §12).",
    )
    parser.add_argument(
        "--mode",
        default="scripted",
        choices=["scripted", "scatter", "model"],
        help="scripted=control, scatter=deterministic divergence, model=live provider",
    )
    parser.add_argument(
        "--seeds",
        default=",".join(DEFAULT_SEEDS),
        help="comma-separated seed words (one per agent)",
    )
    parser.add_argument("--populations", type=int, default=2)
    parser.add_argument("--seed", default="wordseed")
    parser.add_argument("--export", metavar="PATH", help="write the JSON report to PATH")
    args = parser.parse_args()

    report = run_word_seed_experiment(
        session_factory=SessionLocal,
        mode=args.mode,
        seeds=[s for s in (part.strip() for part in args.seeds.split(",")) if s],
        populations=args.populations,
        seed=args.seed,
    )
    print_summary(report)
    if args.export:
        print(f"  exported    : {export_report(report, args.export)}")
    print(f"  replay with : experiment {report['experiment_id']} (ARTIFACT_CREATED events)")


if __name__ == "__main__":
    main()
