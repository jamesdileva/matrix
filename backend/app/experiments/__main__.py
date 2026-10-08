"""CLI: run the lineage experiment against the dev database.

    python -m app.experiments                          # full retention, 100 generations
    python -m app.experiments --mode lossy --export out.json
    python -m app.experiments --mode model             # live ModelPolicy from FLOOD_MODEL_*

Replay afterwards: the experiment id prints on completion; the report
can be rebuilt from persisted events alone.
"""

from __future__ import annotations

import argparse

from app.experiments.lineage import (
    DEFAULT_GENERATIONS,
    export_report,
    print_summary,
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
    args = parser.parse_args()

    report = run_lineage_experiment(
        session_factory=SessionLocal,
        mode=args.mode,
        generations=args.generations,
        seed=args.seed,
    )
    print_summary(report)
    if args.export:
        print(f"  exported    : {export_report(report, args.export)}")
    print(f"  replay with : experiment {report['experiment_id']}")


if __name__ == "__main__":
    main()
