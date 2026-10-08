"""CLI: run the lineage experiment against the dev database.

    python -m app.experiments                          # full retention, 100 generations
    python -m app.experiments --mode lossy --export out.json
    python -m app.experiments --mode model             # live ModelPolicy from FLOOD_MODEL_*
    python -m app.experiments --generations 10000      # the S12 stress scale (mock minds)
    python -m app.experiments --resume 4 --generations 10000

`--checkpoint-every` and `--retention` are the S12 scale switches;
resume continues a checkpointed run from its latest checkpoint.
"""

from __future__ import annotations

import argparse

from app.experiments.lineage import (
    DEFAULT_GENERATIONS,
    export_report,
    print_summary,
    resume_lineage_experiment,
    run_lineage_experiment,
)
from app.persistence.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments",
        description="Run the 100-generation lineage experiment (guide §11).",
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "lossy", "altering", "negating", "new", "model"],
        help="full=control, the others produce known drift, model=a live ModelPolicy",
    )
    parser.add_argument("--generations", type=int, default=DEFAULT_GENERATIONS)
    parser.add_argument("--seed", default="lineage")
    parser.add_argument("--export", metavar="PATH", help="write the JSON report to PATH")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=None,
        help="write a resumable checkpoint every N generations (S12)",
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=None,
        help="cap the world's in-memory event window at N events (S12)",
    )
    parser.add_argument(
        "--resume",
        type=int,
        default=None,
        metavar="EXPERIMENT_ID",
        help="continue a checkpointed run from its latest checkpoint (S12)",
    )
    args = parser.parse_args()

    if args.resume is not None:
        report = resume_lineage_experiment(
            SessionLocal,
            args.resume,
            generations=args.generations,
            checkpoint_every=args.checkpoint_every,
            event_retention=args.retention,
        )
    else:
        report = run_lineage_experiment(
            session_factory=SessionLocal,
            mode=args.mode,
            generations=args.generations,
            seed=args.seed,
            checkpoint_every=args.checkpoint_every,
            event_retention=args.retention,
        )
    print_summary(report)
    if args.export:
        print(f"  exported    : {export_report(report, args.export)}")
    print(f"  replay with : experiment {report['experiment_id']}")


if __name__ == "__main__":
    main()
