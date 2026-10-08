"""Experiments: repeatable runs of the world with a measurable outcome.

The first one is the 100-generation lineage experiment (guide §11 /
roadmap S11); the runner, metrics, replay and export live in
``lineage.py``.
"""

from app.experiments.lineage import (
    DEFAULT_FACTS,
    DEFAULT_GENERATIONS,
    export_report,
    print_summary,
    replay_lineage_experiment,
    resume_lineage_experiment,
    run_lineage_experiment,
)

__all__ = [
    "DEFAULT_FACTS",
    "DEFAULT_GENERATIONS",
    "export_report",
    "print_summary",
    "replay_lineage_experiment",
    "resume_lineage_experiment",
    "run_lineage_experiment",
]
