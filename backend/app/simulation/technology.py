"""Technology: recipes, construction patterns, tools, inventions (S29).

A recipe is data — a name, its material inputs, and what crafting it
produces. A construction pattern is data too: a set of blocks with
offsets around an anchor. Before this sprint the block costs were
bare constants in ``actions``; now they are the world's public
knowledge, and a mind can *learn* them.

What makes culture cumulative is the join between the two places
knowledge lives. ``World`` keeps the registries (every recipe the
world has ever known, every pattern) and per-entity *known* sets —
that is what the ``craft`` action checks. An agent's ``knowledge``
list is what birth carries to a child; the engine parses the
``recipe:``/``pattern:`` prefixes out of it and grants them to the
child. A discovery therefore outlives the agent that made it: the
descendant builds with the ancestor's pattern without rediscovering
it, which is the sprint's verification.

Inventions are combinations: two known items — a recipe and another
recipe — make one new thing, from a deterministic table. The first
tool is the axe: carrying one doubles a gather, the smallest honest
proof that a discovery is *useful*.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recipe:
    """A way to make a thing: materials in, object out."""

    name: str
    inputs: dict = field(default_factory=dict)  # resource kind -> amount
    produces: str = ""  # the object type crafting it places in hand
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a recipe needs a name")
        for kind, amount in self.inputs.items():
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
                raise ValueError(f"recipe {self.name!r} input {kind} must be >= 1")
        if not isinstance(self.produces, str) or not self.produces.strip():
            raise ValueError(f"recipe {self.name!r} must produce something")

    def affordable_by(self, ledger: dict) -> bool:
        return all(ledger.get(kind, 0) >= amount for kind, amount in self.inputs.items())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "inputs": dict(self.inputs),
            "produces": self.produces,
            "description": self.description,
        }


@dataclass(frozen=True)
class Pattern:
    """A construction pattern: blocks at offsets around an anchor."""

    name: str
    blocks: tuple = ()  # (dx, dy, block type), relative to the anchor
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a pattern needs a name")
        if not self.blocks:
            raise ValueError(f"pattern {self.name!r} needs at least one block")
        for block in self.blocks:
            if not isinstance(block, (tuple, list)) or len(block) != 3:
                raise ValueError(f"pattern {self.name!r} has a malformed block: {block!r}")
            dx, dy, block_type = block
            if (
                not isinstance(dx, int)
                or not isinstance(dy, int)
                or isinstance(dx, bool)
                or isinstance(dy, bool)
                or not isinstance(block_type, str)
                or not block_type
            ):
                raise ValueError(f"pattern {self.name!r} has a malformed block: {block!r}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "blocks": [list(block) for block in self.blocks],
            "description": self.description,
        }


# The world's public knowledge: the block costs of S18, now as data,
# plus the first tool.
BASE_RECIPES: dict[str, Recipe] = {
    recipe.name: recipe
    for recipe in (
        Recipe("wood_block", {"wood": 1}, "wood_block", "a wall you can carry"),
        Recipe("stone_block", {"stone": 1}, "stone_block", "a heavier wall"),
        Recipe("door", {"wood": 1}, "door", "a passage that can be shut"),
        Recipe("wood_axe", {"wood": 2}, "axe", "carry it and a gather cuts deeper"),
    )
}

TOOLS: dict[str, dict] = {
    # object type -> the effect it grants its carrier
    "axe": {"gather": 2},
}

# Deterministic inventions: two known items make one new thing. Keys
# are the sorted pair of knowledge strings ("recipe:<name>").
INVENTIONS: dict[tuple[str, str], Recipe | Pattern] = {
    ("recipe:wood_axe", "recipe:wood_block"): Pattern(
        "shelter_ring",
        # Clockwise from the top-left, so a builder walking the
        # *outside* of the ring can lay it without crossing its own
        # work (the same guarantee S19's house script relies on).
        (
            (0, 0, "wood_block"), (1, 0, "wood_block"), (2, 0, "wood_block"),
            (3, 0, "wood_block"),
            (3, 1, "wood_block"), (3, 2, "wood_block"), (3, 3, "wood_block"),
            (2, 3, "wood_block"), (1, 3, "wood_block"), (0, 3, "wood_block"),
            (0, 2, "wood_block"), (0, 1, "wood_block"),
        ),
        "a closed ring: shelter, not just a wall",
    ),
    ("recipe:door", "recipe:wood_block"): Recipe(
        "gate", {"wood": 2}, "door", "a door in the builders' own pattern"
    ),
}

# The knowledge grammar. A knowledge string with one of these prefixes
# names world technology; anything else is plain knowledge (S10).
RECIPE_PREFIX = "recipe:"
PATTERN_PREFIX = "pattern:"


def knowledge_item(thing: Recipe | Pattern) -> str:
    """The knowledge string that carries a recipe or a pattern."""
    prefix = RECIPE_PREFIX if isinstance(thing, Recipe) else PATTERN_PREFIX
    return f"{prefix}{thing.name}"


def is_technology(knowledge: str) -> bool:
    """Whether a knowledge string names world technology (not a fact)."""
    return isinstance(knowledge, str) and knowledge.startswith(
        (RECIPE_PREFIX, PATTERN_PREFIX)
    )


def invention_for(first: str, second: str) -> Recipe | Pattern | None:
    """What combining two known items makes, if anything (deterministic)."""
    return INVENTIONS.get(tuple(sorted((first, second))))
