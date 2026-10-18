"""Language evolution (S42): populations that invent shared symbols.

Speech exists (S21) and routes (S28), but every message is already in a
natural language nobody had to invent. This module gives a world a
*lexicon*: a repertoire that maps a concept to an invented symbol, grows
as speakers name things, and spreads when listeners adopt what they hear.

Three properties the sprint must hold (roadmap S42):

- **shared vocabulary can emerge** — lexicons are per agent; agreement is
  measured as the Jaccard distance between their concept→symbol pairs, so
  convergence is observable, not assumed;
- **messages remain parseable** — encoding only replaces known concept
  words, and decoding is its exact inverse, so ``decode(encode(text))``
  is always ``text``;
- **language changes can be tracked** — every invention and adoption is a
  history entry (tick, concept, old value) and a timeline event.

Symbols are invented deterministically from a supplied RNG, so a seeded
conversation produces the same language on every run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The concept vocabulary a world can name. Words outside it pass through
# speech untouched — a language only encodes what it has words for.
CONCEPTS: tuple[str, ...] = (
    "light", "dark", "water", "stone", "tree", "rain", "fire",
    "food", "home", "path", "void", "seed", "root", "ash",
    "door", "echo",
)

_ONSETS = ("k", "t", "m", "r", "s", "sh", "n", "v", "l", "d", "g", "p")
_VOWELS = ("a", "e", "i", "o", "u")

_WORD = re.compile(r"[A-Za-z0-9']+")


def concepts_in(text: str) -> list[str]:
    """The concept words present in a message, lowercased and deduplicated."""
    seen = {word.lower() for word in _WORD.findall(text)}
    return sorted(seen & set(CONCEPTS))


def _new_symbol(taken: set[str], rng) -> str:
    """A pronounceable symbol not already in use, and never a concept."""
    for _ in range(10_000):
        syllables = rng.choice((2, 2, 3))
        candidate = "".join(
            rng.choice(_ONSETS) + rng.choice(_VOWELS) for _ in range(syllables)
        )
        if candidate not in taken and candidate not in CONCEPTS:
            return candidate
    raise RuntimeError("could not invent a fresh symbol")  # pragma: no cover


@dataclass
class Lexicon:
    """One agent's repertoire: concept -> invented symbol, plus its history."""

    entries: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    # --- inspection ---------------------------------------------------

    def symbol_for(self, concept: str) -> str | None:
        return self.entries.get(concept)

    def concepts(self) -> list[str]:
        return sorted(self.entries)

    def symbols(self) -> list[str]:
        return sorted(self.entries.values())

    def to_dict(self) -> dict:
        return {"entries": dict(self.entries), "history": list(self.history)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Lexicon":
        data = data or {}
        entries = data.get("entries")
        history = data.get("history")
        return cls(
            entries={
                concept: symbol
                for concept, symbol in (entries if isinstance(entries, dict) else {}).items()
                if isinstance(concept, str) and isinstance(symbol, str)
            },
            history=[item for item in (history or []) if isinstance(item, dict)],
        )

    # --- change -------------------------------------------------------

    def invent(self, concept: str, rng, *, tick: int = 0, actor: int | None = None) -> tuple[str, bool]:
        """Name a concept, unless it already has a name. Returns (symbol, new)."""
        existing = self.entries.get(concept)
        if existing is not None:
            return existing, False
        symbol = _new_symbol(set(self.entries.values()), rng)
        self.entries[concept] = symbol
        self.history.append(
            {"tick": tick, "kind": "invented", "concept": concept,
             "symbol": symbol, "actor": actor}
        )
        return symbol, True

    def adopt(
        self,
        concept: str,
        symbol: str,
        *,
        tick: int = 0,
        actor: int | None = None,
        source: int | None = None,
    ) -> bool:
        """Take a heard symbol into the repertoire. Returns True if changed."""
        if not concept or not symbol:
            return False
        if symbol in CONCEPTS:
            return False  # a symbol must never shadow a plain concept word
        previous = self.entries.get(concept)
        if previous == symbol:
            return False
        self.entries[concept] = symbol
        self.history.append(
            {
                "tick": tick,
                "kind": "adopted" if previous is None else "replaced",
                "concept": concept,
                "symbol": symbol,
                "previous": previous,
                "actor": actor,
                "source": source,
            }
        )
        return True

    # --- translation --------------------------------------------------

    def encode(
        self,
        text: str,
        *,
        rng=None,
        tick: int = 0,
        actor: int | None = None,
    ) -> tuple[str, list[dict]]:
        """Replace known concept words with symbols; invent missing ones.

        A word outside ``CONCEPTS`` is left as written. With no ``rng``,
        an unknown concept also passes through (pure encoding); with one,
        the lexicon grows. Returns ``(encoded, innovations)``.
        """
        innovations: list[dict] = []

        def replace(match: re.Match) -> str:
            word = match.group(0)
            concept = word.lower()
            if concept not in CONCEPTS:
                return word
            symbol = self.entries.get(concept)
            if symbol is None:
                if rng is None:
                    return word
                symbol, invented = self.invent(
                    concept, rng, tick=tick, actor=actor
                )
                if invented:
                    innovations.append({"concept": concept, "symbol": symbol})
            return symbol

        return _WORD.sub(replace, text), innovations

    def decode(self, text: str) -> str:
        """The inverse of encoding for this repertoire.

        Concept matching is case-insensitive, so an encoded word decodes
        to its lowercase concept; every other word is untouched.
        """
        inverse = {symbol: concept for concept, symbol in self.entries.items()}

        def replace(match: re.Match) -> str:
            word = match.group(0)
            return inverse.get(word, word)

        return _WORD.sub(replace, text)

    # --- comparison ---------------------------------------------------

    def agreement(self, other: "Lexicon") -> float:
        """Jaccard similarity of two repertoires, as concept→symbol pairs.

        Two empty lexicons agree perfectly (both speak plain language);
        a shared word counts only when the symbol matches.
        """
        mine = set(self.entries.items())
        theirs = set(other.entries.items())
        union = mine | theirs
        if not union:
            return 1.0
        return round(len(mine & theirs) / len(union), 6)

    def shared_with(self, other: "Lexicon") -> list[str]:
        """Concepts both agents encode with the same symbol."""
        return sorted(
            concept
            for concept, symbol in self.entries.items()
            if other.entries.get(concept) == symbol
        )


def mean_agreement(lexicons: list[Lexicon]) -> float:
    """Mean pairwise agreement across a set of repertoires."""
    scores = [
        left.agreement(right)
        for index, left in enumerate(lexicons)
        for right in lexicons[index + 1 :]
    ]
    return round(sum(scores) / len(scores), 6) if scores else 1.0
