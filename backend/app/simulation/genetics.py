"""Agent genetics (S41): a bounded genome that drifts from parent to child.

Inheritance (S10) carries a free-form ``traits`` dict the parent authors;
nothing changes on its own. The genome is the other half: a fixed set of
named numeric genes that every agent has, that pass from parent to child
on their own, and that change only by small bounded mutations. A lineage
becomes a slowly drifting thing without a trait ever running away.

Three properties the sprint must hold (roadmap S41):

- **traits remain bounded** — every gene is clamped to its spec's range on
  every read *and* every write, so no caller can push one out of range;
- **inheritance is traceable** — a child's genome is its parent's genome
  mutated, and every birth records both the parent and the child genome;
- **mutations are recorded** — ``inherit`` returns every change as a
  ``{gene, from, to}`` record, emitted on the timeline and on the birth.

Mutation is deterministic: run under the same seed and the same history
of births, the same genomes and the same mutations come out (roadmap's
determinism contract). The RNG is supplied by the caller — the engine
seeds one from the world — so this module stays a pure function of its
inputs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# How often, per gene, a mutation is attempted at each birth.
DEFAULT_MUTATION_RATE = 0.25


@dataclass(frozen=True)
class GeneSpec:
    """One gene's contract: its name, its bounds, and how far it may move."""

    name: str
    minimum: float = 0.0
    maximum: float = 1.0
    default: float = 0.5
    max_step: float = 0.05
    description: str = ""

    def clamp(self, value: float) -> float:
        """The one place a gene value is allowed to exist."""
        return round(min(max(float(value), self.minimum), self.maximum), 6)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "min": self.minimum,
            "max": self.maximum,
            "default": self.default,
            "max_step": self.max_step,
            "description": self.description,
        }


# The shelf: five behavioural dispositions, all in [0, 1]. A slow drift of
# at most 0.05 per birth keeps a lineage recognisable across generations.
GENE_SPECS: tuple[GeneSpec, ...] = (
    GeneSpec("curiosity", 0.0, 1.0, 0.6, 0.05, "how far a mind strays from what it knows"),
    GeneSpec("diligence", 0.0, 1.0, 0.5, 0.05, "how readily a mind keeps working"),
    GeneSpec("sociability", 0.0, 1.0, 0.5, 0.05, "how much a mind seeks others out"),
    GeneSpec("boldness", 0.0, 1.0, 0.4, 0.05, "how willing a mind is to take risks"),
    GeneSpec("patience", 0.0, 1.0, 0.5, 0.05, "how long a mind waits before giving up"),
)

_BY_NAME: dict[str, GeneSpec] = {spec.name: spec for spec in GENE_SPECS}
GENE_NAMES: tuple[str, ...] = tuple(spec.name for spec in GENE_SPECS)


@dataclass
class Genome:
    """An agent's genes: a value for every spec, always in range."""

    values: dict[str, float]

    @classmethod
    def default(cls) -> "Genome":
        return cls({spec.name: spec.clamp(spec.default) for spec in GENE_SPECS})

    @classmethod
    def from_dict(cls, data: dict | None) -> "Genome":
        """Tolerant parse: unknown genes dropped, missing filled, out-of-range clamped.

        Consistent with the inheritance package's contract (S10): a
        malformed genome is repaired, never fatal.
        """
        genome = cls.default()
        if isinstance(data, dict):
            for name, value in data.items():
                spec = _BY_NAME.get(name)
                if spec is None or isinstance(value, bool):
                    continue
                try:
                    genome.values[name] = spec.clamp(value)
                except (TypeError, ValueError):
                    continue
        return genome

    def __getitem__(self, name: str) -> float:
        return self.values[name]

    def to_dict(self) -> dict:
        """Stable, spec-ordered, JSON-safe form."""
        return {
            spec.name: self.values.get(spec.name, spec.clamp(spec.default))
            for spec in GENE_SPECS
        }

    def distance(self, other: "Genome") -> float:
        """Mean absolute gene difference — how far two genomes sit apart."""
        if not GENE_NAMES:
            return 0.0
        total = sum(
            abs(self.values.get(name, 0.0) - other.values.get(name, 0.0))
            for name in GENE_NAMES
        )
        return round(total / len(GENE_NAMES), 6)

    def inherit(
        self, rng: random.Random, *, mutation_rate: float = DEFAULT_MUTATION_RATE
    ) -> tuple["Genome", list[dict]]:
        """Return ``(child_genome, mutations)`` — this genome, slowly changed.

        Each gene mutates with probability ``mutation_rate`` by at most its
        spec's ``max_step``, then is clamped. Every net change is returned
        as a ``{"gene", "from", "to"}`` record, so mutations are never
        silent.
        """
        child = Genome(dict(self.values))
        mutations: list[dict] = []
        for spec in GENE_SPECS:
            parent_value = spec.clamp(self.values.get(spec.name, spec.default))
            value = parent_value
            if rng.random() < mutation_rate:
                value = spec.clamp(parent_value + rng.uniform(-spec.max_step, spec.max_step))
            child.values[spec.name] = value
            if value != parent_value:
                mutations.append({"gene": spec.name, "from": parent_value, "to": value})
        return child, mutations


def mutation_catalog() -> dict:
    """The library's public form for the API: the shelf and the defaults."""
    return {
        "genes": [spec.to_dict() for spec in GENE_SPECS],
        "mutation_rate": DEFAULT_MUTATION_RATE,
    }
