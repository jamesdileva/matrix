"""S29 â€” cumulative culture: a parent's discovery, a descendant's use.

One generation discovers (a recipe, a tool, a construction pattern)
and the next builds with all of it without rediscovering any. The
roadmap's verification, run as a scenario: the parent discovers
recipes, crafts the world's first axe, invents the shelter-ring
pattern from an axe and a wall, and has a child; the child crafts
its own axe from the inherited recipe, builds the inherited pattern,
and gathers deeper than a tool-less agent can.

The scripted policies are instruments, not minds: they know the
scenario's own grammar (which recipe name to say, where the pattern
anchors) because the scenario defines it. The *data* they use â€” the
recipes and the pattern â€” is genuinely inherited, which is the point.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app.config.settings import settings
from app.models.provider import ModelProvider
from app.persistence.models import ExperimentModel, WorldModel
from app.persistence.repositories import DatabaseEventRecorder
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.policies import WanderPolicy
from app.simulation.technology import Pattern, knowledge_item
from app.simulation.world import Position, Terrain, World

WORLD_SIZE = 24
TECHNOLOGY_SYSTEM_PROMPT = (
    "You are an agent inside a flat grid world with trees. Your task: "
    "discover, craft, and build the technology you inherit. Use "
    "'discover' to learn a recipe from your materials, 'craft' with a "
    "known recipe to make a tool, and 'invent' with two known items to "
    "make something new. Build blocks with 'build'. Decide from the "
    "observation each tick. Reply with JSON only: "
    '{"action": {"action": "discover|craft|invent|build|gather|move|look", '
    '"recipe": string, "a": string, "b": string, "block": "wood_block", '
    '"direction": "north|south|east|west"}, '
    '"goal_update": string|null, "thought_summary": string|null, '
    '"message": string|null, '
    '"inheritance": {"traits": {}, "knowledge": [string], '
    '"message": string|null, "cultural_artifacts": []}} '
    "The world validates every action."
)

ANCHOR = (10, 10)  # where the invented pattern stands


class InventorPolicy:
    """The parent's script: discover, craft, invent, bequeath.

    The route is the scenario's own vocabulary â€” the parent needs
    three discoveries (door, axe, wall), then crafts the axe, then
    combines the axe and the wall into the shelter-ring pattern. It
    also declares what it hands its child, through the decision
    contract's inheritance field (S10).
    """

    def __init__(self) -> None:
        self._index = 0
        self.discoveries = 0
        self.crafts = 0
        self.inventions = 0
        self.tool_yield = 0

    def decide(self, observation: dict) -> dict:
        step = self._index
        if step >= 5:
            return {"action": {"action": "look"}}
        self._index += 1
        if step < 3:
            self.discoveries += 1
            return {"action": {"action": "discover"}}
        if step == 3:
            self.crafts += 1
            return {"action": {"action": "craft", "recipe": "wood_axe"}}
        if step == 4:
            self.inventions += 1
            return {
                "action": {
                    "action": "invent",
                    "a": "recipe:wood_axe",
                    "b": "recipe:wood_block",
                },
                "inheritance": {
                    "traits": {},
                    "knowledge": ["recipe:wood_axe", "pattern:shelter_ring"],
                    "message": "the axe recipe and the ring pattern are ours now",
                    "cultural_artifacts": [],
                },
            }


class HeirPolicy:
    """The descendant's script: use what was inherited, not rediscover it.

    It crafts the axe from the recipe it was born knowing (never
    discovering), gathers with it beside its home tree, then builds the
    inherited pattern around the anchor by walking the ring's outside
    â€” the safe route S19's house builder uses, driven by the pattern's
    *data* rather than a hand-written shape.
    """

    def __init__(
        self, pattern: Pattern, anchor: tuple[int, int], start: tuple[int, int]
    ) -> None:
        self.script = pattern_script(start, anchor, pattern)
        self.crafts = 0
        self.blocks_built = 0
        self.tool_yield = 0
        self._stage = 0
        self._wood_before = 0
        self._index = 0

    def decide(self, observation: dict) -> dict:
        if self._stage == 0:
            self._stage = 1
            self.crafts += 1
            return {"action": {"action": "craft", "recipe": "wood_axe"}}
        if self._stage == 1:
            self._stage = 2
            self._wood_before = observation["resources"].get("wood", 0)
            return {"action": {"action": "gather", "resource": "wood"}}
        if self._stage == 2:
            # The gather landed: its yield is what the ledger gained.
            self._stage = 3
            self.tool_yield = (
                observation["resources"].get("wood", 0) - self._wood_before
            )
        if self._index >= len(self.script):
            return {"action": {"action": "look"}}
        verb, direction = self.script[self._index]
        self._index += 1
        if verb == "build":
            self.blocks_built += 1
            return {
                "action": {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                    "purpose": "shelter",
                }
            }
        return {"action": {"action": "move", "direction": direction}}
        verb, direction = self.script[self._index]
        self._index += 1
        if verb == "build":
            self.blocks_built += 1
            return {
                "action": {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                    "purpose": "shelter",
                }
            }
        return {"action": {"action": "move", "direction": direction}}


def pattern_script(
    start: tuple[int, int], anchor: tuple[int, int], pattern: Pattern
) -> list[tuple[str, str]]:
    """A move/build script laying a pattern by walking its outside.

    Blocks are laid clockwise (the pattern's own data order), each
    built from the stand cell outside it, and the walk between stands
    turns the *outer* corner â€” so on a cleared lot the route never
    crosses a block the builder has already laid. The builder starts
    at ``start``.
    """
    directions = {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}
    x0, y0 = anchor
    blocks = [(x0 + dx, y0 + dy, block) for dx, dy, block in pattern.blocks]
    x_min, x_max = min(b[0] for b in blocks) - 1, max(b[0] for b in blocks) + 1
    y_min, y_max = min(b[1] for b in blocks) - 1, max(b[1] for b in blocks) + 1
    script: list[tuple[str, str]] = []
    here = start

    def walk_to(target: tuple[int, int]) -> None:
        nonlocal here
        while here[0] != target[0]:
            step = 1 if target[0] > here[0] else -1
            script.append(("move", directions[(step, 0)]))
            here = (here[0] + step, here[1])
        while here[1] != target[1]:
            step = 1 if target[1] > here[1] else -1
            script.append(("move", directions[(0, step)]))
            here = (here[0], here[1] + step)

    for x, y, _block in blocks:
        # Which side of the ring is this block on? The stand is one
        # cell outside it, on that side.
        if y == y_min + 1:
            stand = (x, y - 1)
        elif x == x_max - 1:
            stand = (x + 1, y)
        elif y == y_max - 1:
            stand = (x, y + 1)
        else:
            stand = (x - 1, y)
        if here[0] != stand[0] and here[1] != stand[1]:
            # Turn the corner on the way round, not through the work.
            corner = (
                (x_max, y_min) if here[1] == y_min
                else (x_max, y_max) if here[0] == x_max
                else (x_min, y_max) if here[1] == y_max
                else (x_min, y_min)
            )
            walk_to(corner)
        walk_to(stand)
        script.append(("build", directions[(x - stand[0], y - stand[1])]))
    return script


def _build_world(seed: str, bus: EventBus) -> World:
    """A flat lot with trees beside the parent's start (S29's workshop)."""
    world = World(
        str(seed),
        WORLD_SIZE,
        WORLD_SIZE,
        terrain=[[Terrain.FLOOR] * WORLD_SIZE for _ in range(WORLD_SIZE)],
        event_bus=bus,
    )
    for dx, dy in ((0, 1), (1, 1), (2, 1)):
        world.place_object("tree", Position(2 + dx, 2 + dy), properties={"quantity": 4, "resource": "wood"})
    return world


def _tick_metrics(engine: Engine, actor_id: int) -> dict:
    world = engine.world
    return {
        "discoveries": sum(
            1
            for e in world.events
            if e.type == EventTypes.INVENTION
            and e.actor_id == actor_id
            and e.payload.get("kind") == "discovery"
        ),
        "inventions": sum(
            1
            for e in world.events
            if e.type == EventTypes.INVENTION
            and e.actor_id == actor_id
            and e.payload.get("kind") == "invention"
        ),
        "crafts": sum(
            1 for e in world.events if e.type == EventTypes.CRAFT and e.actor_id == actor_id
        ),
    }


def run_cumulative_culture(
    *,
    session_factory,
    mode: str = "scripted",
    seed: str = "culture",
    max_ticks: int = 120,
) -> dict:
    """The scenario: one generation's discoveries become the next's.

    ``mode`` swaps the minds (``scripted`` calibration or ``model``
    through the S07 seam); the scenario engine never changes.
    """
    if mode not in ("scripted", "model"):
        raise ValueError(f"unknown mode {mode!r}; expected scripted or model")
    name = f"culture-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="culture",
            seed=str(seed),
            status="running",
            model_configuration={"mode": mode},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id

    bus = EventBus()
    world = _build_world(seed, bus)
    engine = Engine(world, population_id=1)

    provider: ModelProvider | None = None
    if mode == "model":
        from app.models.config import provider_from_settings

        provider = provider_from_settings(settings)

    # The parent: starts beside its trees, with enough wood to
    # experiment with and to build the first tool.
    parent_policy: object = (
        ModelPolicy(provider, system_prompt=TECHNOLOGY_SYSTEM_PROMPT)
        if provider is not None
        else InventorPolicy()
    )
    parent = Agent(agent_id=1, policy=parent_policy, observation_radius=3)
    engine.spawn_agent(parent, Position(2, 2))
    world.credit_resource(parent.agent_id, "wood", 4)

    # --- the parent's generation: discover, craft, invent, gather ---
    for _tick in range(1, max_ticks + 1):
        engine.step()
        if mode == "scripted" and parent_policy._index >= 5:
            break
    parent_metrics = _tick_metrics(engine, parent.agent_id)
    # Gather with the tool the parent crafted (a tree is adjacent).
    gather = engine.world.execute_action(parent.agent_id, {"action": "gather", "resource": "wood"})
    tool_yield = gather.data.get("amount", 0) if gather.ok else 0

    # --- the descendant: same world, one generation later ---
    if mode == "scripted":
        pattern = world.patterns.get("shelter_ring") or _fallback_pattern()
        child_spot = Position(3, 2)  # beside the home tree, adjacent to it
        child_policy = HeirPolicy(pattern, ANCHOR, (3, 2))
    child = engine.create_child(parent.agent_id, policy=child_policy, position=child_spot)
    # Materials enough for the inherited recipe and the ring.
    world.credit_resource(child.agent_id, "wood", 14)
    structures_before = len(world.structures())
    for _tick in range(1, max_ticks + 1):
        engine.step()
        if (
            mode == "scripted"
            and child_policy._index >= len(child_policy.script)
        ):
            break
    child_metrics = _tick_metrics(engine, child.agent_id)
    structures = len(world.structures()) - structures_before
    # The descendant's tool yield is what its own gather gained (the
    # policy measured it beside the home tree, before it walked to
    # the site); a post-build gather would be measuring the wrong
    # thing â€” distance, not tools.
    child_tool_yield = getattr(child_policy, "tool_yield", 0)

    record = {
        "experiment_id": experiment_id,
        "mode": mode,
        "parent": {
            **parent_metrics,
            "tool_yield": tool_yield,
            "knowledge": list(parent.knowledge),
        },
        "child": {
            "id": child.agent_id,
            "generation": child.generation,
            **child_metrics,
            "blocks_built": getattr(child_policy, "blocks_built", 0),
            "structures_built": structures,
            "tool_yield": child_tool_yield,
            "inherited_knowledge": list(child.knowledge),
            "known_recipes": world.known_recipes(child.agent_id),
            "known_patterns": world.known_patterns(child.agent_id),
        },
        "cumulative": {
            "parent_discoveries": parent_metrics["discoveries"],
            "child_discoveries": child_metrics["discoveries"],
            "child_crafted_without_discovering": child_metrics["discoveries"] == 0
            and child_metrics["crafts"] >= 1,
            "descendant_built_the_pattern": getattr(child_policy, "blocks_built", 0) >= 12,
            "descendant_used_the_tool": child_tool_yield >= 2,
        },
    }
    with session_factory() as session:
        experiment_row = session.get(ExperimentModel, experiment_id)
        experiment_row.status = "completed"
        experiment_row.finished_at = datetime.now(timezone.utc)
        experiment_row.model_configuration = {
            "mode": mode,
            **record["cumulative"],
        }
        session.commit()
    return record


def _fallback_pattern() -> Pattern:
    return Pattern("shelter_ring", ((0, 0, "wood_block"),), "placeholder")


def print_report(record: dict) -> None:
    parent = record["parent"]
    child = record["child"]
    print(f"cumulative culture ({record['mode']}):")
    print(
        f"  parent: {parent['discoveries']} discoveries, {parent['crafts']} crafts, "
        f"{parent['inventions']} inventions, gathered {parent['tool_yield']} wood in one stroke"
    )
    print(
        f"  child (gen {child['generation']}): {child['discoveries']} discoveries, "
        f"{child['crafts']} crafts, {child['blocks_built']} blocks, "
        f"{child['structures_built']} structures, gathered {child['tool_yield']}"
    )
    cumulative = record["cumulative"]
    print(
        f"  culture is cumulative: "
        f"{'yes' if cumulative['child_crafted_without_discovering'] else 'no'} "
        f"(descendant built the pattern: "
        f"{'yes' if cumulative['descendant_built_the_pattern'] else 'no'}; "
        f"used the tool: {'yes' if cumulative['descendant_used_the_tool'] else 'no'})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.technology",
        description="Run the cumulative-culture scenario (roadmap S29).",
    )
    parser.add_argument("--mode", default="scripted", choices=["scripted", "model"])
    parser.add_argument("--seed", default="culture")
    parser.add_argument("--max-ticks", type=int, default=120)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    record = run_cumulative_culture(
        session_factory=SessionLocal,
        mode=args.mode,
        seed=args.seed,
        max_ticks=args.max_ticks,
    )
    print_report(record)


if __name__ == "__main__":
    main()
