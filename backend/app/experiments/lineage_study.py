"""S32 — multiple independent lineages: comparing divergent histories.

One lineage is an anecdote; several run from identical starting
conditions are an experiment. The study runner starts N lineages with
the same founder's facts and the same minds, varying only the seed —
with scripted calibrations the runs are deterministic, which makes the
first study a null hypothesis (same seed, same history) and any seeded
variation a controlled difference; with model minds the same harness
measures genuine divergence.

The roadmap's measures, computed so runs are *comparable*: every value
is a fraction, a count of a shared vocabulary or a summary statistic
(mean, stdev, min, max, n), never a raw run-specific tally.

- cultural convergence: mean pairwise Jaccard of the final cultures.
- divergence: the complement, plus facts unique to each run.
- information loss: the fraction of the founder's facts no longer
  standing in the final generation.
- strategies: each lineage's retention profile — which of retained /
  altered / contradicted / new dominates its transmission — and how
  far profiles sit from each other.
- vocabulary: per-run distinct token counts, the union and shared
  vocabularies across runs, and growth against the founder's.

Export writes the whole study — configuration, every run, the
cross-run statistics — to one JSON file, so a study can leave the
simulation and live in a paper.
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
from datetime import datetime, timezone
from pathlib import Path

from app.experiments.lineage import DEFAULT_FACTS, run_lineage_experiment, tokens
from app.persistence.models import ExperimentModel

STUDY_SCENARIO = "lineage_study"
RUN_SCENARIO = "lineage_study_run"

# The comparison vocabulary: the roadmap's measures, in words.
MEASURES = (
    "cultural_convergence",
    "divergence",
    "information_loss",
    "strategies",
    "vocabulary",
)


def _summary(values: list[float]) -> dict:
    """Comparable statistics for one measure: n, mean, spread, range."""
    if not values:
        return {"n": 0, "mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": round(stats.fmean(values), 4),
        "stdev": round(stats.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mean_pairwise(sets: list[set]) -> float:
    if len(sets) < 2:
        return 1.0  # a single run converges with itself
    pairs = [
        _jaccard(first, second)
        for index, first in enumerate(sets)
        for second in sets[index + 1 :]
    ]
    return round(stats.fmean(pairs), 4)


def _dominant(profile: dict) -> str | None:
    """The strategy that dominates a retention profile, if any does."""
    if not any(profile.values()):
        return None
    return max(profile, key=profile.get)


def _profile(final: dict, original_count: int) -> dict:
    """A run's retention profile: what its transmission did, as fractions."""
    received = final.get("facts_received", 0)
    if not received:
        return {"retained": 0.0, "altered": 0.0, "contradicted": 0.0, "new": 0.0}
    return {
        "retained": round(len(final.get("retained", [])) / received, 4),
        "altered": round(len(final.get("altered", [])) / received, 4),
        "contradicted": round(len(final.get("contradicted", [])) / received, 4),
        "new": round(len(final.get("new", [])) / received, 4),
    }


def _dominant(profile: dict) -> str | None:
    """Which strategy a profile mostly is: the largest fraction."""
    if not any(profile.values()):
        return None
    return max(profile, key=profile.get)


def _run_measures(report: dict, originals: list[str]) -> dict:
    """One run, normalized onto the study's measure space."""
    final = report.get("final") or {}
    knowledge = final.get("retained", []) + final.get("altered", []) + final.get(
        "contradicted", []
    ) + final.get("new", [])
    vocabulary = set()
    for fact in knowledge:
        vocabulary |= tokens(fact)
    profile = _profile(final, len(originals))
    lost = len(final.get("lost", []))
    return {
        "experiment_id": report["experiment_id"],
        "name": report["name"],
        "seed": report["seed"],
        "mode": report["mode"],
        "generations": report["generations"],
        "knowledge_final": sorted(knowledge),
        "vocabulary": sorted(vocabulary),
        "vocabulary_size": len(vocabulary),
        "profile": profile,
        "dominant_strategy": _dominant(profile),
        "information_loss": round(lost / len(originals), 4) if originals else 0.0,
        "facts_lost": lost,
        "avg_similarity": final.get("avg_similarity", 0.0),
        "avg_message_length": round(
            stats.fmean([t["message_length"] for t in report["trajectory"]]), 2
        )
        if report["trajectory"]
        else 0.0,
    }


def compare_runs(runs: list[dict], originals: list[str]) -> dict:
    """The cross-run measures: convergence, divergence, loss, strategies,
    vocabulary — each with its statistics across the runs."""
    knowledge_sets = [set(run["knowledge_final"]) for run in runs]
    vocabularies = [set(run["vocabulary"]) for run in runs]
    knowledge_convergence = _mean_pairwise(knowledge_sets)
    vocabulary_convergence = _mean_pairwise(vocabularies)
    union_vocabulary = set().union(*vocabularies) if vocabularies else set()
    shared_vocabulary = set.intersection(*vocabularies) if vocabularies else set()
    unique_per_run = [
        len(culture - set().union(*knowledge_sets[:index] + knowledge_sets[index + 1 :]))
        if len(knowledge_sets) > 1
        else 0
        for index, culture in enumerate(knowledge_sets)
    ]

    profiles = [run["profile"] for run in runs]
    strategy_keys = ("retained", "altered", "contradicted", "new")
    if len(profiles) > 1:
        spread = round(
            stats.fmean(
                sum(abs(first[key] - second[key]) for key in strategy_keys) / 2
                for index, first in enumerate(profiles)
                for second in profiles[index + 1 :]
            ),
            4,
        )
    else:
        spread = 0.0

    consensus = {
        key: round(stats.fmean([profile[key] for profile in profiles]), 4)
        if profiles
        else 0.0
        for key in strategy_keys
    }

    return {
        "runs": len(runs),
        "cultural_convergence": {
            "facts": knowledge_convergence,
            "vocabulary": vocabulary_convergence,
        },
        "divergence": {
            "facts": round(1 - knowledge_convergence, 4),
            "vocabulary": round(1 - vocabulary_convergence, 4),
            "unique_facts_per_run": _summary([float(value) for value in unique_per_run]),
        },
        "information_loss": _summary([run["information_loss"] for run in runs]),
        "strategies": {
            "consensus_profile": consensus,
            "per_run": [
                {
                    "seed": run["seed"],
                    "dominant": _dominant(run["profile"]),
                    **run["profile"],
                }
                for run in runs
            ],
            "profile_spread": spread,
        },
        "vocabulary": {
            "per_run": [len(run["vocabulary"]) for run in runs],
            "union": len(union_vocabulary),
            "shared": len(shared_vocabulary),
            "shared_fraction": round(len(shared_vocabulary) / len(union_vocabulary), 4)
            if union_vocabulary
            else 0.0,
            "founder": len(set().union(*[tokens(fact) for fact in originals]))
            if originals
            else 0,
            "growth": round(
                stats.fmean(
                    [
                        len(set(run["vocabulary"]))
                        / len(set().union(*[tokens(fact) for fact in originals]))
                        for run in runs
                    ]
                ),
                4,
            )
            if originals
            and set().union(*[tokens(fact) for fact in originals])
            else 0.0,
        },
    }


def run_study(
    *,
    session_factory,
    runs: int = 3,
    mode: str = "full",
    generations: int = 12,
    facts: list[str] | None = None,
    seed: str = "study",
    export_path: str | None = None,
    vary: str = "seed",
    models: list[str] | None = None,
) -> dict:
    """Run the study: N lineages, one comparison, one export.

    ``vary`` is the axis the roadmap names: ``seed`` (identical minds,
    different seeds — the determinism control) or ``model`` (identical
    seeds, different minds — ``models`` names each run's mode). The
    founder's facts never vary: the starting conditions are the
    experiment's constant.
    """
    if runs < 1:
        raise ValueError(f"a study needs at least one run, got {runs}")
    if vary not in ("seed", "model"):
        raise ValueError(f"unknown vary axis {vary!r}; expected seed or model")
    if vary == "model" and runs != len(models or []):
        raise ValueError(
            f"varying the mind needs one mode per run: {runs} runs, {len(models or [])} modes"
        )
    originals = list(facts if facts is not None else DEFAULT_FACTS)
    run_modes = list(models) if vary == "model" else [mode] * runs

    name = f"study-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=STUDY_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={
                "mode": mode,
                "vary": vary,
                "models": run_modes if vary == "model" else None,
                "runs": runs,
                "generations": generations,
                "measures": list(MEASURES),
            },
            generation_limit=generations,
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    run_records = []
    for index in range(runs):
        # Identical starting conditions; only the named axis varies.
        report = run_lineage_experiment(
            session_factory=session_factory,
            mode=run_modes[index],
            generations=generations,
            facts=originals,
            seed=seed if vary == "model" else f"{seed}-{index}",
            name=f"{name}-{index}",
        )
        run_records.append(_run_measures(report, originals))

    comparison = compare_runs(run_records, originals)
    study = {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": STUDY_SCENARIO,
        "seed": seed,
        "mode": mode,
        "vary": vary,
        "generations": generations,
        "originals": originals,
        "runs": [
            {
                "index": index,
                "experiment_id": record["experiment_id"],
                "seed": record["seed"],
                "mode": record["mode"],
                "generations": record["generations"],
                "information_loss": record["information_loss"],
                "dominant_strategy": record["dominant_strategy"],
                "vocabulary_size": record["vocabulary_size"],
                "avg_similarity": record["avg_similarity"],
            }
            for index, record in enumerate(run_records)
        ],
        "run_records": run_records,
        "comparison": comparison,
        "measures": list(MEASURES),
    }

    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": mode,
            "vary": vary,
            "models": run_modes if vary == "model" else None,
            "runs": runs,
            "generations": generations,
            "measures": list(MEASURES),
            "comparison": comparison,
            "run_experiment_ids": [record["experiment_id"] for record in run_records],
        }
        session.commit()

    if export_path:
        study["export_path"] = export_study(study, export_path)
    return study


def export_study(study: dict, path: str) -> str:
    """Write the whole study to one JSON file; returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(study, indent=2, sort_keys=False), encoding="utf-8"
    )
    return str(target)


def print_summary(study: dict) -> None:
    comparison = study["comparison"]
    axis = (
        "the mind (" + ", ".join(run["mode"] for run in study["runs"]) + ")"
        if study["vary"] == "model"
        else "the seed"
    )
    print(
        f"lineage study {study['name']!r}: {comparison['runs']} runs from identical "
        f"starts, varying {axis}"
    )
    print(
        f"  cultural convergence: facts {comparison['cultural_convergence']['facts']} "
        f"(1.0 = identical cultures)"
    )
    divergence = comparison["divergence"]
    print(
        f"  divergence: facts {divergence['facts']}, vocabulary {divergence['vocabulary']}, "
        f"{divergence['unique_facts_per_run']['mean']} unique facts per run"
    )
    loss = comparison["information_loss"]
    print(
        f"  information loss: {loss['mean']} ± {loss['stdev']} "
        f"(min {loss['min']}, max {loss['max']}, n {loss['n']})"
    )
    strategies = comparison["strategies"]
    consensus = strategies["consensus_profile"]
    print(
        f"  strategies: consensus "
        + ", ".join(f"{key} {value}" for key, value in consensus.items())
        + f"; spread {strategies['profile_spread']}"
    )
    vocabulary = comparison["vocabulary"]
    print(
        f"  vocabulary: {vocabulary['per_run']} tokens per run, union {vocabulary['union']}, "
        f"shared {vocabulary['shared']} ({vocabulary['shared_fraction']})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.lineage_study",
        description="Run multiple independent lineages and compare them (roadmap S32).",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mode", default="full")
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--seed", default="study")
    parser.add_argument(
        "--vary",
        default="seed",
        choices=["seed", "model"],
        help="what differs between runs: the seed, or the mind",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated modes, one per run, when --vary model",
    )
    parser.add_argument("--export", default=None, help="write the study as JSON here")
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    models = args.models.split(",") if args.models else None
    if args.vary == "model" and not models:
        # The default comparison: the retentive, the lossy and the
        # inventor — cycling when the study asks for more runs.
        base = ["full", "lossy", "new"]
        models = [base[index % len(base)] for index in range(args.runs)]

    study = run_study(
        session_factory=SessionLocal,
        runs=args.runs,
        mode=args.mode,
        generations=args.generations,
        seed=args.seed,
        export_path=args.export,
        vary=args.vary,
        models=models,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
