"""S36 Ã¢â‚¬â€ the reconstruction experiment: ask a descendant to rebuild
its ancestor.

The roadmap's procedure, as a runnable scenario:

1. a lineage grows from the founder's culture to generation N
   (the S11 engine Ã¢â‚¬â€ the same modes, the same engine, any depth);
2. **Agent 0 is hidden** Ã¢â‚¬â€ the reconstructor never sees the originals.
   They exist in this module for *scoring* and nowhere else: the
   scripted reconstructor takes only the records it was handed, and a
   model reconstructor is prompted with only those records;
3. the descendant receives **limited records** Ã¢â‚¬â€ the final culture
   passed through one of S35's codecs (full, compressed, or a coded
   transmission), so the archive is degraded before the historian
   ever opens it;
4. the descendant reconstructs Ã¢â‚¬â€ verbatim (the scripted control) or in
   its own words (a model mind through the S07 seam, which also
   states its confidence).

The measures are the roadmap's four:

- **exact recovery** Ã¢â‚¬â€ the originals present verbatim in the
  reconstruction;
- **semantic recovery** Ã¢â‚¬â€ graded: each original's best token-Jaccard
  against anything reconstructed, averaged;
- **invented history** Ã¢â‚¬â€ reconstructed facts no original is close to:
  what the descendant made up;
- **confidence** Ã¢â‚¬â€ what the reconstructor claims (model), or its
  measured exact recovery (scripted control).

The end goal is a quantified failure profile, and the study is the
roadmap's answer: reconstruction failure, as a function of how much
the lineage kept and how much of the archive survived.
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import settings
from app.experiments.compression import CODECS, Codebook
from app.experiments.lineage import ALTER_THRESHOLD, tokens
from app.models.decision import DecisionError, extract_json_object
from app.models.provider import ModelRequest
from app.persistence.models import ExperimentModel

STUDY_SCENARIO = "reconstruction_study"
RUN_SCENARIO = "reconstruction"

RECONSTRUCTORS = ("scripted", "model")
# The archive qualities the descendant might be handed: intact,
# truncated, or symbols with no codebook. "full" is the verbatim
# codec under a name the roadmap's procedure would use.
RECORD_KINDS = ("full", "compressed", "symbolic")
_CODEC_FOR_RECORDS = {"full": "verbose"}


def _jaccard(first: set, second: set) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


# ----------------------------------------------------------------------
# The reconstruction
# ----------------------------------------------------------------------


def scripted_reconstruction(records: list[str]) -> list[str]:
    """The control historian: it hands back what the archive holds.

    It cannot see the originals Ã¢â‚¬â€ its only input is the records Ã¢â‚¬â€ so
    whatever it invents is exactly the archive's own invention.
    """
    return list(records)


async def model_reconstruction(provider, records: list[str]) -> dict:
    """A model historian: reconstruct from the records, state confidence."""
    listing = "\n".join(f"- {record}" for record in records)
    prompt = (
        "You are the last descendant of a long lineage. These are the "
        "only records that survived:\n" + listing + "\n\n"
        "From them alone, reconstruct the original set of facts your "
        "ancestor began with, and state how confident you are. Reply "
        "with JSON only: "
        '{"reconstructed": ["fact", ...], "confidence": 0.0-1.0}'
    )
    request = ModelRequest(observation={"records": list(records)},
                           system_prompt=prompt)
    response = await provider.generate(request)
    try:
        data = extract_json_object(response.text)
    except DecisionError as exc:
        raise ValueError(f"the historian's output is unusable: {exc}") from exc
    reconstructed = data.get("reconstructed")
    if not isinstance(reconstructed, list) or not all(
        isinstance(fact, str) for fact in reconstructed
    ):
        raise ValueError(f"the historian's reconstruction is malformed: {reconstructed!r}")
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError(f"the historian's confidence is malformed: {confidence!r}")
    return {
        "reconstructed": [str(fact) for fact in reconstructed],
        "confidence": round(float(confidence), 4),
    }


# ----------------------------------------------------------------------
# The measures
# ----------------------------------------------------------------------


def measure_reconstruction(
    originals: list[str],
    reconstructed: list[str],
    confidence: float | None,
) -> dict:
    """Score a reconstruction against the (hidden) originals."""
    original_tokens = [tokens(fact) for fact in originals]
    reconstructed_tokens = [tokens(fact) for fact in reconstructed]

    exact = sum(1 for fact in originals if fact in reconstructed)
    semantic = []
    for tokens_ in original_tokens:
        if reconstructed_tokens:
            semantic.append(
                max(_jaccard(tokens_, other) for other in reconstructed_tokens)
            )
        else:
            semantic.append(0.0)
    invented = [
        fact
        for fact, tokens_ in zip(reconstructed, reconstructed_tokens)
        if max((_jaccard(tokens_, original) for original in original_tokens), default=0.0)
        < ALTER_THRESHOLD
    ]
    return {
        "exact_recovery": round(exact / len(originals), 4) if originals else 0.0,
        "semantic_recovery": round(stats.fmean(semantic), 4) if semantic else 0.0,
        "invented_history": invented,
        "invented_count": len(invented),
        "confidence": confidence,
    }


# ----------------------------------------------------------------------
# The scenario
# ----------------------------------------------------------------------


def _limited_records(final_culture: list[str], kind: str, message: str) -> list[str]:
    """Degrade the archive into what the descendant is handed.

    - ``full`` â€” the culture as it stands (the intact archive);
    - ``compressed`` â€” the truncated form (the partial archive);
    - ``symbolic`` â€” symbols only, with the codebook *lost*: the
      descendant holds coded records and no key, which is the
      catastrophic case an undeciphered history actually presents.
    """
    codec = CODECS.get(_CODEC_FOR_RECORDS.get(kind, kind))
    if codec is None:
        raise ValueError(f"unknown record kind {kind!r}; expected one of {list(RECORD_KINDS)}")
    if kind != "symbolic":
        book = Codebook()
        for fact in final_culture:
            for token in fact.split():
                book.symbol_for(token, None)
        encoded = codec.encode_facts(final_culture, book)
        encoded_message = codec.encode_message(message, book)
        records = codec.decode_facts(encoded, book)
        if encoded_message.strip():
            records = records + [codec.decode_message(encoded_message, book)]
        return records

    # The codebook is burned with the ancestor: encode with the
    # lineage's book, hand over the symbols as the records.
    book = Codebook()
    for fact in final_culture:
        for token in fact.split():
            book.symbol_for(token, None)
    encoded = codec.encode_facts(final_culture, book)
    encoded_message = codec.encode_message(message, book)
    records = list(encoded)
    if encoded_message.strip():
        records.append(encoded_message)
    return records


def run_reconstruction(
    *,
    session_factory,
    mode: str = "full",
    records: str = "full",
    reconstructor: str = "scripted",
    generations: int = 200,
    facts: list[str] | None = None,
    message: str = "the river runs east, remember the grove and the fire",
    seed: str = "reconstruction",
) -> dict:
    """Run the procedure: hide the ancestor, limit the records, rebuild."""
    from app.experiments.lineage import run_lineage_experiment

    if records not in RECORD_KINDS:
        raise ValueError(f"unknown record kind {records!r}; expected one of {list(RECORD_KINDS)}")
    if reconstructor not in RECONSTRUCTORS:
        raise ValueError(
            f"unknown reconstructor {reconstructor!r}; expected one of {list(RECONSTRUCTORS)}"
        )

    # The lineage: the ancestor's culture travelling to generation N.
    lineage = run_lineage_experiment(
        session_factory=session_factory,
        mode=mode,
        generations=generations,
        facts=facts,
        seed=seed,
        name=f"lineage-{seed}",
    )
    originals = lineage["originals"]
    final = lineage["final"]
    final_culture = (
        final.get("retained", []) + final.get("altered", []) + final.get("new", [])
    )

    # Step 3: the archive the descendant is handed Ã¢â‚¬â€ degraded once, here.
    archive = _limited_records(final_culture, records, final.get("message") or message)

    # Step 4: reconstruct. The originals never reach this step.
    claimed_confidence: float | None = None
    if reconstructor == "model":
        from app.models.config import provider_from_settings

        provider = provider_from_settings(settings)
        import asyncio

        outcome = asyncio.run(model_reconstruction(provider, archive))
        rebuilt = outcome["reconstructed"]
        claimed_confidence = outcome["confidence"]
    else:
        rebuilt = scripted_reconstruction(archive)
        claimed_confidence = None  # the control reports measured, not claimed

    scored = measure_reconstruction(originals, rebuilt, claimed_confidence)
    if reconstructor == "scripted":
        # The control's confidence is exactly what it recovered.
        scored["confidence"] = scored["exact_recovery"]

    name = f"reconstruction-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=RUN_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={
                "mode": mode,
                "records": records,
                "reconstructor": reconstructor,
                "generations": generations,
            },
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    record = {
        "experiment_id": experiment_id,
        "name": name,
        "mode": mode,
        "records": records,
        "reconstructor": reconstructor,
        "generations": generations,
        "lineage_experiment_id": lineage["experiment_id"],
        "archive": archive,
        "reconstructed": rebuilt,
        "measures": scored,
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": mode,
            "records": records,
            "reconstructor": reconstructor,
            "measures": scored,
        }
        session.commit()
    return record


def run_study(
    *,
    session_factory,
    mode: str = "full",
    records: list[str] | None = None,
    generations: int = 200,
    facts: list[str] | None = None,
    seed: str = "reconstruction",
    export_path: str | None = None,
) -> dict:
    """The failure profile: reconstruction under every record quality.

    The default lineage retains its culture so the *archive* is the
    axis being measured; pass a degrading mode to compound both.
    """
    record_kinds = list(records or RECORD_KINDS)
    for kind in record_kinds:
        if kind not in RECORD_KINDS:
            raise ValueError(f"unknown record kind {kind!r}; expected one of {list(RECORD_KINDS)}")

    name = f"study-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=STUDY_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={"mode": mode, "records": record_kinds},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    runs = []
    for index, kind in enumerate(record_kinds):
        runs.append(
            run_reconstruction(
                session_factory=session_factory,
                mode=mode,
                records=kind,
                generations=generations,
                facts=facts,
                seed=f"{seed}-{index}",
            )
        )

    profile = {
        "exact_recovery": {
            run["records"]: run["measures"]["exact_recovery"] for run in runs
        },
        "semantic_recovery": {
            run["records"]: run["measures"]["semantic_recovery"] for run in runs
        },
        "invented_count": {
            run["records"]: run["measures"]["invented_count"] for run in runs
        },
        "confidence": {run["records"]: run["measures"]["confidence"] for run in runs},
        "mean_exact_recovery": round(
            stats.fmean([run["measures"]["exact_recovery"] for run in runs]), 4
        )
        if runs
        else 0.0,
        "mean_semantic_recovery": round(
            stats.fmean([run["measures"]["semantic_recovery"] for run in runs]), 4
        )
        if runs
        else 0.0,
        "mean_invented": round(
            stats.fmean([run["measures"]["invented_count"] for run in runs]), 2
        )
        if runs
        else 0.0,
    }

    study = {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": STUDY_SCENARIO,
        "mode": mode,
        "seed": seed,
        "generations": generations,
        "records": record_kinds,
        "runs": [
            {
                "records": run["records"],
                "experiment_id": run["experiment_id"],
                "lineage_experiment_id": run["lineage_experiment_id"],
                "measures": run["measures"],
                "reconstructed": run["reconstructed"],
            }
            for run in runs
        ],
        "profile": profile,
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "mode": mode,
            "records": record_kinds,
            "profile": profile,
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
        f"reconstruction study {study['name']!r}: mode {study['mode']}, "
        f"{study['generations']} generations, records {study['records']}"
    )
    for run in study["runs"]:
        measures = run["measures"]
        print(
            f"  records {run['records']}: exact {measures['exact_recovery']}, "
            f"semantic {measures['semantic_recovery']}, invented "
            f"{measures['invented_count']}, confidence {measures['confidence']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.reconstruction",
        description="Hide the ancestor; let the descendant rebuild it (roadmap S36).",
    )
    parser.add_argument("--mode", default="full", help="the lineage's transmission mode")
    parser.add_argument(
        "--records",
        default=None,
        help="comma-separated record kinds; default all (full,compressed,symbolic)",
    )
    parser.add_argument("--generations", type=int, default=200)
    parser.add_argument("--seed", default="reconstruction")
    parser.add_argument("--export", default=None)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    study = run_study(
        session_factory=SessionLocal,
        mode=args.mode,
        records=args.records.split(",") if args.records else None,
        generations=args.generations,
        seed=args.seed,
        export_path=args.export,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
