"""Language emergence study (S42).

A small, deterministic demonstration that a shared vocabulary *can* emerge
from independent invention and conversation — the roadmap's first check
for this sprint.

The setup is deliberately minimal: every agent names the same concepts
privately (and invents different symbols doing so), then agents hear each
other and adopt what they hear. Each round measures agreement, so the
study produces a convergence curve rather than a single verdict.
"""

from __future__ import annotations

import random

from app.simulation.language import CONCEPTS, Lexicon, mean_agreement

DEFAULT_CONCEPTS: tuple[str, ...] = (
    "water", "stone", "tree", "fire", "food", "home", "path", "light",
)
DEFAULT_AGENTS = 6
DEFAULT_ROUNDS = 12


def run_language_experiment(
    *,
    agents: int = DEFAULT_AGENTS,
    rounds: int = DEFAULT_ROUNDS,
    concepts: tuple[str, ...] = DEFAULT_CONCEPTS,
    seed: str | int = "language",
    attention: int | None = None,
) -> dict:
    """Independent invention, then conversation, measuring convergence.

    ``attention`` caps how many words a listener takes from one speaker in
    a round (``None`` means all of them). Lower attention slows
    convergence — a useful knob for a laboratory, not a requirement.
    """
    if agents < 2:
        raise ValueError("a language needs at least two speakers")
    if rounds < 0:
        raise ValueError("rounds cannot be negative")
    unknown = [concept for concept in concepts if concept not in CONCEPTS]
    if unknown:
        raise ValueError(f"unknown concepts: {', '.join(unknown)}")

    rng = random.Random(f"{seed}:language")
    lexicons = [Lexicon() for _ in range(agents)]

    # Phase 1 — private invention. Everyone names the same world, and
    # because no one has heard anyone, the names diverge.
    for lexicon in lexicons:
        for concept in concepts:
            lexicon.invent(concept, rng, tick=0)

    agreement_before = mean_agreement(lexicons)
    vocabulary_before = len({symbol for lexicon in lexicons for symbol in lexicon.symbols()})

    # Phase 2 — transmission. Each agent listens to one other and adopts
    # what it can; speakers change every round, so words travel.
    curve = []
    for round_index in range(1, rounds + 1):
        for listener_index, listener in enumerate(lexicons):
            others = [index for index in range(agents) if index != listener_index]
            speaker_index = rng.choice(others)
            speaker = lexicons[speaker_index]
            heard = [
                (concept, speaker.symbol_for(concept))
                for concept in concepts
                if speaker.symbol_for(concept) is not None
            ]
            rng.shuffle(heard)
            if attention is not None:
                heard = heard[: max(0, attention)]
            for concept, symbol in heard:
                listener.adopt(
                    concept,
                    symbol,
                    tick=round_index,
                    actor=listener_index,
                    source=speaker_index,
                )
        curve.append(mean_agreement(lexicons))

    agreement_after = curve[-1] if curve else agreement_before
    vocabulary_after = len({symbol for lexicon in lexicons for symbol in lexicon.symbols()})
    shared = set.intersection(
        *[set(lexicon.entries.items()) for lexicon in lexicons]
    ) if lexicons else set()
    return {
        "agents": agents,
        "rounds": rounds,
        "concepts": list(concepts),
        "attention": attention,
        "seed": str(seed),
        "agreement_before": agreement_before,
        "agreement_after": agreement_after,
        "agreement_by_round": curve,
        "vocabulary_before": vocabulary_before,
        "vocabulary_after": vocabulary_after,
        "shared_words": sorted(
            [{"concept": concept, "symbol": symbol} for concept, symbol in shared],
            key=lambda item: (item["concept"], item["symbol"]),
        ),
        "changes": sum(len(lexicon.history) for lexicon in lexicons),
        "converged": agreement_after == 1.0,
        "lexicons": [
            {"agent_id": index, "entries": dict(lexicon.entries)}
            for index, lexicon in enumerate(lexicons)
        ],
    }
