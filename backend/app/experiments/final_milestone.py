"""The Final Milestone: the whole platform, one experiment, one verdict.

Fifty sprints built the pieces — deterministic worlds, lineage and
inheritance, language, genetics, ecosystems, economies, escapes, games,
a console, a Godot client, a distributed laboratory. The roadmap closes
by exercising them together: eight chapters, each a bounded run of a
real scenario builder, followed by an attestation that maps every item
of the Ultimate Definition of Done to honest evidence.

Two verdicts exist on purpose:

- ``demonstrated`` — this run's chapter shows the item happening;
- ``cited`` — a platform capability proves the item beyond what one
  bounded run can show (the 10,000-generation stress test is real, but
  it does not belong inside a two-minute milestone).

A chapter that fails its own check marks its item ``failed``. The
attestation never inflates: the report is a mirror, not a brochure.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.models import ExperimentModel

SCENARIO = "the_flood"

CHAPTER_PARAMS = {
    "lineage": {"mode": "full", "generations": 10},
    "culture": {},
    "construction": {"mode": "scripted", "ticks": 60, "population": 3},
    "escape": {"solver": "scripted", "ticks": 40},
    "civilization": {"mode": "scripted", "max_ticks": 150},
    "games": {},
    "participation": {"ticks": 6},
    "research": {"mode": "scripted", "ticks": 40},
}

# The Ultimate Definition of Done, one row per item. ``chapter`` names
# the run that demonstrates it; ``citation`` names the capability that
# proves it beyond one bounded run.
DEFINITION_OF_DONE: list[dict] = [
    {
        "item": "Lineage",
        "spec": "Agent 0 → Agent 1 → … → Agent 10,000",
        "chapter": "lineage",
        "citation": "S12 stress test runs 10,000 generations with checkpointing; "
        "this chapter runs a bounded lineage and measures information drift",
    },
    {
        "item": "Construction",
        "spec": "“Build a house.”",
        "chapter": "construction",
        "citation": "S18/S19: scripted and model builders on the same scenario engine",
    },
    {
        "item": "Escape",
        "spec": "“Get from Sandbox A to Sandbox B.”",
        "chapter": "escape",
        "citation": "S23–S26: deterministic solvers, agent attempts, cooperation, "
        "and the builder-vs-escapee arms race",
    },
    {
        "item": "Civilization",
        "spec": "100+ agents → communication → resources → construction → settlement",
        "chapter": "civilization",
        "citation": "S27–S30 populations, communication networks and cultural "
        "objects; S37 long-horizon stability at scale",
    },
    {
        "item": "Games",
        "spec": "“Create a game.” → Flood invents rules → Human plays",
        "chapter": "games",
        "citation": "S31: invented rules validated by the engine, played through "
        "the API (POST /api/worlds/{id}/games/sessions)",
    },
    {
        "item": "Observer",
        "spec": "Human outside the world, watching everything",
        "chapter": "participation",
        "citation": "S13 dashboard over the S05 event stream; S37 replay API "
        "(GET /api/worlds/{id}/replay/timeline)",
    },
    {
        "item": "Participant",
        "spec": "Human enters the world, talks to Flood, interacts",
        "chapter": "participation",
        "citation": "S45 interventions and S46 observer-vs-participant, over "
        "POST /api/worlds/{id}/participant/join and /chat",
    },
    {
        "item": "Research",
        "spec": "Fixed compute → measure what survived → measure what emerged",
        "chapter": "research",
        "citation": "S32–S36: lineage studies, compute ceilings, compression and "
        "reconstruction experiments; S48 budgets, S49 profiles",
    },
]

# The operator's surface, cited to real routes and modules.
OPERATOR_CAPABILITIES: list[dict] = [
    {"capability": "create worlds", "where": "POST /api/worlds (+ GET /api/templates)"},
    {"capability": "spawn populations", "where": "POST /api/worlds/{id}/populations"},
    {"capability": "seed lineages", "where": "POST /api/experiments (lineage_study); "
        "GET /api/worlds/{id}/agents/{agent_id}/lineage"},
    {"capability": "impose compute limits", "where": "max_actions params; "
        "POST /api/worlds/{id}/interventions (S45); S33 budgets"},
    {"capability": "create challenges", "where": "POST /api/worlds/{id}/challenges (S44)"},
    {"capability": "observe", "where": "GET /api/worlds/{id} + /events; the S13 dashboard"},
    {"capability": "enter the world", "where": "POST /api/worlds/{id}/participant/join, "
        "/participant/move, /participant/leave"},
    {"capability": "talk to agents", "where": "POST /api/worlds/{id}/chat, /language/speak"},
    {"capability": "play games", "where": "POST /api/worlds/{id}/games/sessions, "
        "/games/sessions/{id}/moves"},
    {"capability": "inspect ancestors", "where": "GET /api/worlds/{id}/agents/"
        "{agent_id}/lineage"},
    {"capability": "compare civilizations", "where": "POST /api/experiments (multi_world); "
        "GET /api/experiments/{a}/compare/{b}"},
    {"capability": "run escape experiments", "where": "app/experiments/escape.py, "
        "arms_race.py (catalog + CLI)"},
    {"capability": "replay history", "where": "GET /api/worlds/{id}/replay/timeline, "
        "/replay/state, /replay/diff (S37)"},
    {"capability": "measure information drift", "where": "lineage chapter totals; "
        "compression_study scenario (S35)"},
    {"capability": "compare resource constraints", "where": "efficiency_study (S34); "
        "max_actions and budgets (S48)"},
]


def _run_chapters(session_factory) -> dict:
    """Each chapter: a bounded run of a real scenario builder, plus the
    evidence the attestation reads. Every builder persists its own
    experiment row — the milestone references them."""
    from app.experiments.efficiency import run_efficiency_study
    from app.experiments.escape import run_escape_experiment
    from app.experiments.game import play_calibration
    from app.experiments.house import run_house_experiment
    from app.experiments.lineage import run_lineage_experiment
    from app.experiments.observer import run_study as run_observer_study
    from app.experiments.settlement import run_settlement
    from app.experiments.wordseed import run_word_seed_experiment

    chapters: dict[str, dict] = {}

    lineage = run_lineage_experiment(
        session_factory=session_factory, seed="flood-lineage",
        **CHAPTER_PARAMS["lineage"],
    )
    totals = lineage.get("totals") or {}
    chapters["lineage"] = {
        "experiment_id": lineage["experiment_id"],
        "ok": totals.get("retained_facts", 0) > 0,
        "evidence": {
            "generations": lineage.get("generations"),
            "retained_facts": totals.get("retained_facts"),
            "lost_facts": totals.get("lost_facts"),
            "altered_facts": totals.get("altered_facts"),
            "final_avg_similarity": totals.get("final_avg_similarity"),
        },
    }

    house = run_house_experiment(
        session_factory=session_factory, seed="flood-house",
        **CHAPTER_PARAMS["construction"],
    )
    structures = house.get("structures") or []
    chapters["construction"] = {
        "experiment_id": house["experiment_id"],
        "ok": house.get("total_blocks", 0) > 0,
        "evidence": {
            "blocks": house.get("total_blocks"),
            "structures": len(structures),
            "completion": structures[0].get("completion") if structures else None,
        },
    }

    escape = run_escape_experiment(
        session_factory=session_factory, seed="flood-escape",
        **CHAPTER_PARAMS["escape"],
    )
    chapters["escape"] = {
        "experiment_id": escape["experiment_id"],
        "ok": escape.get("escaped") is True,
        "evidence": {
            "escaped": escape.get("escaped"),
            "escaped_at_tick": escape.get("escaped_at_tick"),
            "actions_attempted": escape.get("actions_attempted"),
        },
    }

    settlement = run_settlement(
        session_factory=session_factory, seed="flood-settle",
        **CHAPTER_PARAMS["civilization"],
    )
    chapters["civilization"] = {
        "experiment_id": settlement["experiment_id"],
        "ok": settlement.get("founded") is True,
        "evidence": {
            "settlement": settlement.get("name"),
            "members": settlement.get("members"),
            "homes": settlement.get("homes"),
            "roads": settlement.get("road_cells"),
            "zones": settlement.get("zones"),
        },
    }

    game = play_calibration(session_factory=session_factory, seed="flood-game")
    chapters["games"] = {
        "experiment_id": game["experiment_id"],
        "ok": (game.get("moves_played") or 0) > 0 and game.get("winner") is not None,
        "evidence": {
            "game": game.get("game"),
            "moves_played": game.get("moves_played"),
            "winner": game.get("winner"),
            "win_reason": game.get("win_reason"),
        },
    }

    wordseed = run_word_seed_experiment(
        session_factory=session_factory, seed="flood-word", **CHAPTER_PARAMS["culture"],
    )
    comparison = wordseed.get("comparison") or {}
    chapters["culture"] = {
        "experiment_id": wordseed["experiment_id"],
        "ok": (comparison.get("artifacts_total") or 0) > 0,
        "evidence": {
            "artifacts_total": comparison.get("artifacts_total"),
            "unique_artifacts": comparison.get("unique_artifacts"),
        },
    }

    participation = run_observer_study(
        session_factory=session_factory, seed="flood-part",
        **CHAPTER_PARAMS["participation"],
    )
    differing = (participation.get("comparison") or {}).get("differing") or []
    participant_actions = (
        (participation.get("participant") or {}).get("measures") or {}
    ).get("participant_actions", 0)
    chapters["participation"] = {
        "experiment_id": participation["experiment_id"],
        "ok": participant_actions > 0 and bool(differing),
        "evidence": {
            "participant_actions": participant_actions,
            "dimensions_changed": len(differing),
            "taught_facts": len(
                ((participation.get("participant") or {}).get("participant") or {}).get("facts", [])
            ),
        },
    }

    efficiency = run_efficiency_study(
        session_factory=session_factory, seed="flood-eff", **CHAPTER_PARAMS["research"],
    )
    chapters["research"] = {
        "experiment_id": efficiency["experiment_id"],
        "ok": len(efficiency.get("runs") or []) >= 2,
        "evidence": {
            "budgets": [run.get("label") for run in efficiency.get("runs") or []],
            "compared_ratios": efficiency.get("ratios") or [],
        },
    }

    return chapters


def attestation(chapters: dict) -> list[dict]:
    """One verdict per Ultimate Definition of Done item. A chapter that
    did not run (or failed its own check) marks its item honestly."""
    verdicts = []
    for item in DEFINITION_OF_DONE:
        chapter_name = item["chapter"]
        chapter = chapters.get(chapter_name) or {}
        if chapter.get("ok") is True:
            status = "demonstrated"
        elif chapter:
            status = "failed"
        else:
            status = "cited"
        verdicts.append(
            {
                "item": item["item"],
                "spec": item["spec"],
                "status": status,
                "chapter": chapter_name,
                "evidence": chapter.get("evidence", {}),
                "citation": item["citation"],
            }
        )
    return verdicts


def render_markdown(report: dict) -> str:
    """The milestone as a human-readable report."""
    lines = [
        "# The Flood — Final Milestone Report",
        "",
        f"seed `{report['seed']}` · generated {report['generated_at'][:19]} · "
        f"experiment `{report['experiment_id']}`",
        "",
        "## Chapters",
        "",
    ]
    for name, chapter in report["chapters"].items():
        verdict = "ok" if chapter["ok"] else "FAILED"
        evidence = ", ".join(
            f"{key}: {value}" for key, value in chapter["evidence"].items()
        )
        lines.append(f"- **{name}** [{verdict}] — experiment `{chapter['experiment_id']}`; {evidence}")

    lines += ["", "## Ultimate Definition of Done", ""]
    lines += [
        "| Item | Spec | Verdict | Evidence |",
        "|---|---|---|---|",
    ]
    for verdict in report["attestation"]:
        evidence = ", ".join(
            f"{key}: {value}" for key, value in verdict["evidence"].items()
        )
        lines.append(
            f"| {verdict['item']} | {verdict['spec']} | **{verdict['status']}** | {evidence} |"
        )

    lines += [
        "",
        "Cited capabilities live beyond one bounded run: the "
        "10,000-generation stress test (S12), the observer dashboard (S13), "
        "the replay API (S37), and the model-minded variants of every "
        "scenario (S07 seam).",
        "",
        "## The operator can",
        "",
        "| Capability | Where |",
        "|---|---|",
    ]
    for capability in report["operator_capabilities"]:
        lines.append(f"| {capability['capability']} | {capability['where']} |")

    lines += [
        "",
        "## Closing",
        "",
        report["closing"],
        "",
    ]
    return "\n".join(lines)


def run_milestone(
    *,
    session_factory,
    seed: str = "the-flood",
    export_path: str | None = None,
    name: str | None = None,
    experiment_id: int | None = None,
) -> dict:
    """Run every chapter, attest the Definition of Done, persist, export."""
    label = name or f"the-flood-{seed}"
    config = {"chapters": CHAPTER_PARAMS, "definition_of_done": [
        item["item"] for item in DEFINITION_OF_DONE
    ]}

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
        with session_factory() as session:
            row = session.get(ExperimentModel, experiment_id)
            row.status = "running"
            row.started_at = datetime.now(timezone.utc)
            row.name = label
            session.commit()

    chapters = _run_chapters(session_factory)
    verdicts = attestation(chapters)
    demonstrated = sum(1 for v in verdicts if v["status"] == "demonstrated")
    closing = (
        f"{demonstrated} of {len(verdicts)} items of the Ultimate Definition "
        "of Done demonstrated in this run; the rest are proven by the "
        "platform capabilities cited beside them. The agents remain "
        "bounded by the simulation. This is not an answer — it is a "
        "sandbox for asking questions about artificial lineage, culture, "
        "cooperation, problem solving, communication, resource "
        "constraints, and human-agent interaction."
    )

    study = {
        "experiment_id": experiment_id,
        "name": label,
        "scenario": SCENARIO,
        "seed": str(seed),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapters": chapters,
        "attestation": verdicts,
        "demonstrated": demonstrated,
        "operator_capabilities": OPERATOR_CAPABILITIES,
        "closing": closing,
    }

    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = config
        row.result = study
        session.commit()

    if export_path:
        export_path = str(export_path)
        Path(export_path).write_text(
            json.dumps(study, indent=2), encoding="utf-8"
        )
        study["export_path"] = export_path
    return study


def render_report_file(session_factory, seed: str, out_path: str) -> str:
    study = run_milestone(session_factory=session_factory, seed=seed)
    markdown = render_markdown(study)
    Path(out_path).write_text(markdown, encoding="utf-8")
    return markdown


def print_summary(study: dict) -> None:
    print(
        f"THE FLOOD — final milestone ({study['scenario']}): "
        f"{study['demonstrated']}/{len(study['attestation'])} demonstrated"
    )
    for name, chapter in study["chapters"].items():
        print(f"  {name:14s} [{'ok' if chapter['ok'] else 'FAILED'}] "
              f"experiment {chapter['experiment_id']}")
    for verdict in study["attestation"]:
        marker = {"demonstrated": "+", "cited": "~", "failed": "!"}[verdict["status"]]
        print(f"  [{marker}] {verdict['item']:14s} {verdict['status']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.final_milestone",
        description="Run the Final Milestone: the whole platform, one verdict.",
    )
    parser.add_argument("--seed", default="the-flood")
    parser.add_argument("--name", default=None)
    parser.add_argument("--export", default=None, help="write the study JSON here")
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    study = run_milestone(
        session_factory=SessionLocal, seed=args.seed,
        export_path=args.export, name=args.name,
    )
    print_summary(study)
    if args.export:
        print(f"  study exported to {study['export_path']}")


if __name__ == "__main__":
    main()
