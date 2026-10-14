"""S35 — cultural compression: does scarcity breed efficiency?

The experiment restricts inheritance *bandwidth* and watches what a
lineage does with it. Three transmissions of the same seed culture:

- **verbose** — everything passes: the facts verbatim and the message
  unabridged (the control);
- **compressed** — the facts are cut to the first few and the message
  to its first few tokens: a hard bandwidth limit, no cleverness;
- **symbolic** — facts and message become symbols from a learned
  dictionary the lineage builds as it goes, capped in size: a real
  code, and the one that can pay for itself.

The measures are the roadmap's three, all per generation:

- **bits transmitted** — symbols sent times log2(codebook size);
- **retained knowledge** — how much of the founder's facts still
  stands, by the S11 classifier's own rules;
- **reconstruction accuracy** — how much of the original message the
  receiver can rebuild from what arrived, as token Jaccard.

The end goal is a determination: whether repeated scarcity encourages
efficiency. The study answers it with the three columns side by side
— bits saved against knowledge retained and reconstruction lost.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.experiments.lineage import generation_metrics, tokens
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

STUDY_SCENARIO = "compression_study"
RUN_SCENARIO = "compression_lineage"

# The symbol alphabet a symbolic codec draws from, and its cap.
SYMBOLS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@dataclass
class Codebook:
    """A lineage's learned token -> symbol dictionary.

    Shared across generations, so a symbol learned once stays known —
    that is what makes symbolic transmission cumulative rather than
    per-generation noise.
    """

    forward: dict = field(default_factory=dict)  # token -> symbol
    reverse: dict = field(default_factory=dict)  # symbol -> token

    def symbol_for(self, token: str, cap: int | None) -> str:
        known = self.forward.get(token)
        if known is not None:
            return known
        if cap is None or len(self.forward) < cap:
            symbol = SYMBOLS[len(self.forward) % len(SYMBOLS)]
            self.forward[token] = symbol
            self.reverse[symbol] = token
            return symbol
        return "?"  # the dictionary is full: this token cannot be encoded

    def token_for(self, symbol: str) -> str:
        return self.reverse.get(symbol, "?")

    @property
    def size(self) -> int:
        return len(self.forward)


@dataclass(frozen=True)
class Codec:
    """One transmission: how much gets through, and in what form."""

    name: str
    fact_bandwidth: int | None = None  # None = every fact passes
    token_bandwidth: int | None = None  # None = every token passes
    symbolic: bool = False
    vocabulary_cap: int | None = None  # the symbol dictionary's ceiling

    def encode_facts(self, facts: list[str], book: Codebook) -> list[str]:
        chosen = facts if self.fact_bandwidth is None else facts[: self.fact_bandwidth]
        if not self.symbolic:
            return list(chosen)
        return [
            " ".join(book.symbol_for(token, self.vocabulary_cap) for token in fact.split())
            for fact in chosen
        ]

    def decode_facts(self, encoded: list[str], book: Codebook) -> list[str]:
        if not self.symbolic:
            return list(encoded)
        return [
            " ".join(book.token_for(symbol) for symbol in fact.split())
            for fact in encoded
        ]

    def encode_message(self, message: str, book: Codebook) -> str:
        parts = message.split()
        chosen = parts if self.token_bandwidth is None else parts[: self.token_bandwidth]
        if not self.symbolic:
            return " ".join(chosen)
        return " ".join(book.symbol_for(token, self.vocabulary_cap) for token in chosen)

    def decode_message(self, encoded: str, book: Codebook) -> str:
        if not self.symbolic:
            return encoded
        return " ".join(book.token_for(symbol) for symbol in encoded.split())

    # --- the roadmap's "bits / tokens transmitted" ---

    def bits(self, message: str, book: Codebook, vocabulary_size: int | None = None) -> int:
        """The transmission's cost: symbols sent times log2(codebook).

        For a symbolic codec the codebook is its learned dictionary.
        For plain transmission it is the culture's shared vocabulary —
        the words the sender and receiver already agree on, which is
        what "plain language" costs against.
        """
        encoded = self.encode_message(message, book)
        symbols = len(encoded.split())
        if self.symbolic:
            codebook = max(2, book.size)
        else:
            codebook = max(2, vocabulary_size or len(set(message.split())))
        return round(symbols * math.log2(codebook))


# The three transmissions the roadmap names.
CODECS = {
    "verbose": Codec("verbose"),
    "compressed": Codec("compressed", fact_bandwidth=3, token_bandwidth=6),
    "symbolic": Codec("symbolic", symbolic=True, vocabulary_cap=16),
}


def _jaccard(first: set, second: set) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def run_compression_lineage(
    *,
    session_factory,
    codec_name: str = "symbolic",
    generations: int = 12,
    facts: list[str] | None = None,
    message: str = "the river runs east, remember the grove and the fire",
    seed: str = "compression",
) -> dict:
    """One lineage transmitting its culture under one codec."""
    if codec_name not in CODECS:
        raise ValueError(f"unknown codec {codec_name!r}; expected one of {sorted(CODECS)}")
    codec = CODECS[codec_name]
    originals = list(facts if facts is not None else DEFAULT_FOUNDER_FACTS)
    original_tokens = [tokens(fact) for fact in originals]
    message_tokens = tokens(message)

    name = f"compression-{codec_name}-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=RUN_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={"codec": codec_name, "generations": generations},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    bus = EventBus()
    world = World(
        str(seed),
        10,
        10,
        terrain=[[Terrain.FLOOR] * 10 for _ in range(10)],
        event_bus=bus,
    )
    engine = Engine(world, population_id=1)

    book = Codebook()
    # The culture's shared vocabulary: the words a plain transmission
    # draws on, which is what symbolic codes are measured against.
    culture_vocabulary = len(set().union(*[tokens(fact) for fact in originals], tokens(message)))
    trajectory: list[dict] = []
    # The founder carries the seed culture; its message is the first
    # thing transmitted.
    carrier_facts = list(originals)
    carried_message = message
    for generation in range(generations):
        # What this generation transmits, through the codec.
        encoded_facts = codec.encode_facts(carrier_facts, book)
        encoded_message = codec.encode_message(carried_message, book)
        bits = codec.bits(carried_message, book, culture_vocabulary)
        # What the next generation receives: the reconstruction.
        received_facts = codec.decode_facts(encoded_facts, book)
        received_message = codec.decode_message(encoded_message, book)
        accuracy = _jaccard(message_tokens, tokens(received_message))
        trajectory.append(
            {
                "generation": generation,
                **generation_metrics(
                    generation,
                    received_facts,
                    received_message,
                    originals,
                    original_tokens,
                ),
                "bits_transmitted": bits,
                "facts_transmitted": len(encoded_facts),
                "symbols_transmitted": len(encoded_message.split()),
                "codebook_size": book.size,
                "reconstruction_accuracy": round(accuracy, 4),
            }
        )
        carrier_facts, carried_message = received_facts, received_message

    final = trajectory[-1] if trajectory else {}
    retained = len(final.get("retained", []))
    record = {
        "experiment_id": experiment_id,
        "codec": codec_name,
        "generations": generations,
        "message": message,
        "originals": originals,
        "trajectory": trajectory,
        "final": final,
        "totals": {
            "bits_transmitted": sum(t["bits_transmitted"] for t in trajectory),
            "avg_bits_per_generation": round(
                stats.fmean([t["bits_transmitted"] for t in trajectory]), 2
            )
            if trajectory
            else 0.0,
            "symbols_transmitted": sum(t["symbols_transmitted"] for t in trajectory),
            "avg_reconstruction_accuracy": round(
                stats.fmean([t["reconstruction_accuracy"] for t in trajectory]), 4
            )
            if trajectory
            else 0.0,
            "final_reconstruction_accuracy": final.get("reconstruction_accuracy", 0.0),
            "retained_facts_final": retained,
            "retention_rate": round(retained / len(originals), 4) if originals else 0.0,
            "final_codebook_size": final.get("codebook_size", 0),
        },
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "codec": codec_name,
            "totals": record["totals"],
        }
        session.commit()
    return record


DEFAULT_FOUNDER_FACTS = (
    "the river runs east",
    "the grove holds wood",
    "stone lies under the hill",
    "fire warms the cold",
    "the path home is south",
)


def run_study(
    *,
    session_factory,
    codecs: list[str] | None = None,
    generations: int = 12,
    facts: list[str] | None = None,
    message: str = "the river runs east, remember the grove and the fire",
    seed: str = "compression",
    export_path: str | None = None,
) -> dict:
    """Compare the transmissions: the roadmap's three, one lineage each."""
    codecs = list(codecs or CODECS)
    for codec_name in codecs:
        if codec_name not in CODECS:
            raise ValueError(f"unknown codec {codec_name!r}; expected one of {sorted(CODECS)}")

    name = f"study-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario=STUDY_SCENARIO,
            seed=str(seed),
            status="running",
            model_configuration={"codecs": codecs, "generations": generations},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    runs = [
        run_compression_lineage(
            session_factory=session_factory,
            codec_name=codec_name,
            generations=generations,
            facts=facts,
            message=message,
            seed=f"{seed}-{codec_name}",
        )
        for codec_name in codecs
    ]

    def _totals(record: dict) -> dict:
        return record["totals"]

    comparison = {
        "bits_per_generation": {
            record["codec"]: _totals(record)["avg_bits_per_generation"] for record in runs
        },
        "retention_rate": {
            record["codec"]: _totals(record)["retention_rate"] for record in runs
        },
        "reconstruction_accuracy": {
            record["codec"]: _totals(record)["avg_reconstruction_accuracy"] for record in runs
        },
        "final_reconstruction_accuracy": {
            record["codec"]: _totals(record)["final_reconstruction_accuracy"]
            for record in runs
        },
        "bits_saved_vs_verbose": {
            record["codec"]: round(
                1
                - record["totals"]["avg_bits_per_generation"]
                / runs[0]["totals"]["avg_bits_per_generation"],
                4,
            )
            if runs[0]["totals"]["avg_bits_per_generation"]
            else None
            for record in runs
        },
    }
    study = {
        "experiment_id": experiment_id,
        "name": name,
        "scenario": STUDY_SCENARIO,
        "seed": seed,
        "message": message,
        "codecs": codecs,
        "generations": generations,
        "runs": [
            {
                "codec": record["codec"],
                "experiment_id": record["experiment_id"],
                "totals": record["totals"],
                "final_retained": record["final"].get("retained", []),
            }
            for record in runs
        ],
        "comparison": comparison,
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {
            "codecs": codecs,
            "generations": generations,
            "comparison": comparison,
            "run_experiment_ids": [record["experiment_id"] for record in runs],
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
        f"compression study {study['name']!r}: {len(study['runs'])} transmissions "
        f"over {study['generations']} generations"
    )
    for run in study["runs"]:
        totals = run["totals"]
        print(
            f"  {run['codec']}: {totals['avg_bits_per_generation']} bits/generation, "
            f"retention {totals['retention_rate']}, reconstruction "
            f"{totals['avg_reconstruction_accuracy']} "
            f"(final {totals['final_reconstruction_accuracy']})"
        )
    saved = study["comparison"]["bits_saved_vs_verbose"]
    for codec, value in saved.items():
        if codec != "verbose" and value is not None:
            print(f"  {codec} saves {round(value * 100, 1)}% of the bits")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.compression",
        description="Compare transmission bandwidths across lineages (roadmap S35).",
    )
    parser.add_argument("--codecs", default=None, help="comma-separated; default all three")
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--seed", default="compression")
    parser.add_argument("--export", default=None)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    study = run_study(
        session_factory=SessionLocal,
        codecs=args.codecs.split(",") if args.codecs else None,
        generations=args.generations,
        seed=args.seed,
        export_path=args.export,
    )
    print_summary(study)
    if args.export:
        print(f"  exported to {study['export_path']}")


if __name__ == "__main__":
    main()
