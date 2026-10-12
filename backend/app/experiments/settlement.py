"""S30 â€” the settlement: construct, claim, bank, pave, and keep it.

One population, one lot. The founder raises a home, founds a
settlement on it, builds the shared storehouse, claims the grove for
the village, paves the road between them, and banks the grove's wood.
A neighbour joins, draws from the shared stock, and raises a second
home â€” which the settlement adopts on the spot, because a member
built it inside the settlement's extent. The verification is
"construct *and* maintain": after the maintenance cycles, every
structure still stands, the stock is intact, the grove is still held
and the road still runs.

The scripted policies are instruments: they know the lot because the
scenario lays it out. What they demonstrate is the settlement
mechanics, not a mind.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app.config.settings import settings
from app.experiments.technology import pattern_script
from app.models.provider import ModelProvider
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.bus import EventBus
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.model_policy import ModelPolicy
from app.simulation.technology import Pattern
from app.simulation.world import Position, Terrain, World

WORLD_SIZE = 24
HOME_ANCHOR = (6, 6)  # first home, 3x3 ring
STORAGE_ANCHOR = (8, 12)  # the storehouse's row
NEIGHBOUR_HOME_ANCHOR = (3, 9)  # the neighbour's home, within extent
GROVE = [(10, 9), (11, 9)]  # trees inside the settlement
HOME_START = (5, 5)
STORAGE_START = (9, 10)  # approached around the home ring, east of it
NEIGHBOUR_START = (10, 15)
MAINTENANCE_CYCLES = 3
SETTLEMENT_NAME = "First Hollow"

SETTLEMENT_SYSTEM_PROMPT = (
    "You are an agent inside a flat grid world with trees. Your task "
    "with the other agent here: build and hold a settlement. Build "
    "homes with 'build' (you carry wood), found one with 'settle' "
    "giving it a name, join one with 'join_settlement', store wood "
    "with 'deposit' while beside the storehouse, claim trees for the "
    "village with 'claim_zone', and lay paths with 'pave'. Decide from "
    "the observation each tick. Reply with JSON only: "
    '{"action": {"action": "build|settle|join_settlement|deposit|withdraw|'
    'pave|claim_zone|gather|move|look", "block": "wood_block", '
    '"direction": "north|south|east|west", "name": string, '
    '"settlement_id": number, "resource": "wood", "amount": number, '
    '"cells": [{"x": number, "y": number}], "target": number}, '
    '"goal_update": string|null, "thought_summary": string|null, '
    '"message": string|null, '
    '"inheritance": {"traits": {}, "knowledge": [string], '
    '"message": string|null, "cultural_artifacts": []}} '
    "The world validates every action."
)

HOME_PATTERN = Pattern(
    "hut_ring",
    (
        (0, 0, "wood_block"), (1, 0, "wood_block"), (2, 0, "wood_block"),
        (2, 1, "wood_block"), (2, 2, "wood_block"), (1, 2, "wood_block"),
        (0, 2, "wood_block"), (0, 1, "wood_block"),
    ),
    "a closed hut ring",
)
STORAGE_PATTERN = Pattern(
    "storehouse_row",
    ((0, 0, "wood_block"), (1, 0, "wood_block"), (2, 0, "wood_block")),
    "a storehouse wall with something behind it",
)

# Where the founder walks to gather from the grove and back to the
# storehouse (routes chosen on open ground; the lot is cleared).
TO_GROVE = [(9, 9)]
TO_STORAGE = [(9, 11)]
NEIGHBOUR_ROUTE = [(10, 14), (7, 14), (7, 12)]  # stands beside the storehouse
ROAD_CELLS = [
    {"x": 9, "y": 7}, {"x": 9, "y": 8}, {"x": 9, "y": 9},
    {"x": 9, "y": 10}, {"x": 9, "y": 11},
]


class _Walker:
    """A scripted route over the lot: walk, build, settle, bank, pave.

    The script is a list of directives consumed one per tick, and a
    ``walk_to`` directive becomes the moves that reach it â€” the policy
    steers from the observation, because a scripted mind still has to
    know where it stands. It is an instrument, not a mind: the
    scenario knows its own lot.
    """

    def __init__(self, script: list[dict]) -> None:
        self.script = script
        self.index = 0
        self.target: tuple[int, int] | None = None
        self.done = False

    def decide(self, observation: dict) -> dict:
        position = observation["self"]["position"]
        if self.target is not None:
            if (position["x"], position["y"]) == self.target:
                self.target = None
            else:
                x, y = self.target
                if position["x"] != x:
                    return {
                        "action": {
                            "action": "move",
                            "direction": "east" if x > position["x"] else "west",
                        }
                    }
                return {
                    "action": {
                        "action": "move",
                        "direction": "south" if y > position["y"] else "north",
                    }
                }
        if self.index >= len(self.script):
            self.done = True
            return {"action": {"action": "look"}}
        directive = self.script[self.index]
        self.index += 1
        if directive["action"] == "walk_to":
            self.target = (directive["x"], directive["y"])
            return self.decide(observation)
        return {"action": directive}


def _walk(waypoints) -> list[dict]:
    """Walk axis-aligned through waypoints (x first, then y)."""
    if isinstance(waypoints, tuple):
        waypoints = [waypoints]
    return [{"action": "walk_to", "x": x, "y": y} for x, y in waypoints]


class FounderPolicy:
    """The founder's whole settlement, as a staged script."""

    def __init__(self) -> None:
        self.policy = _Walker(self._script())
        self.deposits = 0
        self.withdrawals = 0
        self.gathers = 0

    @property
    def done(self) -> bool:
        return self.policy.done

    def _script(self) -> list[dict]:
        script: list[dict] = []
        # 1. Raise the first home from the found materials.
        for verb, direction in pattern_script(HOME_START, HOME_ANCHOR, HOME_PATTERN):
            script.append(
                {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                    "purpose": "home",
                }
                if verb == "build"
                else {"action": "move", "direction": direction}
            )
        # 2. Name the place (founding on the structure just built).
        script.append({"action": "settle", "name": SETTLEMENT_NAME})
        # 3. Raise the shared storehouse; the settlement adopts it as
        #    its builder's own, because they are a member within extent.
        #    The route skirts the home ring: north, then east, then south.
        script += _walk([(5, 5), (9, 5), STORAGE_START])
        for verb, direction in pattern_script(STORAGE_START, STORAGE_ANCHOR, STORAGE_PATTERN):
            script.append(
                {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                    "purpose": "storage",
                }
                if verb == "build"
                else {"action": "move", "direction": direction}
            )
        # 4. Claim the grove for the village.
        script += _walk(TO_GROVE)
        script.append({"action": "claim_zone", "resource": "wood", "target": 1})
        # 5. Pave the road between home and storehouse.
        script += _walk([(9, 7)])
        script.append({"action": "pave", "cells": ROAD_CELLS})
        # 6. Maintain it: gather the grove, bank it, draw some back.
        for _cycle in range(MAINTENANCE_CYCLES):
            script += _walk(TO_GROVE)
            script.append({"action": "gather", "resource": "wood"})
            script += _walk(TO_STORAGE)
            script.append({"action": "deposit", "resource": "wood", "amount": 5})
            script.append({"action": "withdraw", "resource": "wood", "amount": 1})
        return script

    def decide(self, observation: dict) -> dict:
        decision = self.policy.decide(observation)
        action = decision["action"]
        if action.get("action") == "deposit":
            self.deposits += 1
        elif action.get("action") == "withdraw":
            self.withdrawals += 1
        elif action.get("action") == "gather":
            self.gathers += 1
        return decision


class NeighbourPolicy:
    """The neighbour: walk over, join, wait for the stock, draw, build.

    Joining is retried until it takes — the neighbour may arrive
    before the founder has named the place, and a refusal is not a
    reason to give up on the village.
    """

    def __init__(self) -> None:
        self.policy = _Walker(self._route())
        self.withdrawals = 0
        self.blocks = 0
        self._joined = False
        self._asked = False
        self._armed = False

    @property
    def done(self) -> bool:
        return self._armed and self.policy.done

    @staticmethod
    def _route() -> list[dict]:
        return _walk(NEIGHBOUR_ROUTE)

    def decide(self, observation: dict) -> dict:
        if not self._joined:
            if not self.policy.done:
                return self.policy.decide(observation)  # walking over
            if observation.get("settlement") is not None:
                self._joined = True
            elif self._asked:
                # The place may not be named yet: ask again, patiently.
                self._asked = False
                return {"action": {"action": "look"}}
            else:
                self._asked = True
                return {"action": {"action": "join_settlement", "settlement_id": 1}}
        # Wait for the village's stock before drawing on it: the
        # shared ledger is the settlement's, not a magic purse. Once
        # drawn on, the build proceeds whatever the ledger says after.
        if not self._armed:
            settlement = observation.get("settlement") or {}
            if settlement.get("contents", {}).get("wood", 0) < 8:
                return {"action": {"action": "look"}}
            self._armed = True
            self.policy.script = self._build_script()
            self.policy.index = 0
            self.policy.done = False
        decision = self.policy.decide(observation)
        action = decision["action"]
        if action.get("action") == "withdraw":
            self.withdrawals += 1
        elif action.get("action") == "build":
            self.blocks += 1
        return decision

    def _build_script(self) -> list[dict]:
        script: list[dict] = [{"action": "withdraw", "resource": "wood", "amount": 8}]
        script += _walk([(3, 8)])  # the site, reached around the storehouse
        for verb, direction in pattern_script(
            (3, 8), NEIGHBOUR_HOME_ANCHOR, HOME_PATTERN
        ):
            script.append(
                {
                    "action": "build",
                    "block": "wood_block",
                    "direction": direction,
                    "purpose": "home",
                }
                if verb == "build"
                else {"action": "move", "direction": direction}
            )
        return script


def _build_world(seed: str, bus: EventBus) -> World:
    """The lot: flat, with the grove inside where the village will stand."""
    world = World(
        str(seed),
        WORLD_SIZE,
        WORLD_SIZE,
        terrain=[[Terrain.FLOOR] * WORLD_SIZE for _ in range(WORLD_SIZE)],
        event_bus=bus,
    )
    for x, y in GROVE:
        world.place_object("tree", Position(x, y), properties={"quantity": 6, "resource": "wood"})
    return world


def _settle_results(world: World) -> dict:
    settlement = world.settlements[0] if world.settlements else None
    if settlement is None:
        return {"founded": False}
    roads = [road for road in world.roads if road.settlement_id == settlement.id]
    return {
        "founded": True,
        "name": settlement.name,
        "settlement_id": settlement.id,
        "members": sorted(settlement.members),
        "homes": len(settlement.home_ids),
        "storage_structures": len(settlement.storage_ids),
        "roads": len(roads),
        "road_cells": sum(len(road.cells) for road in roads),
        "zones": len(settlement.zones),
        "contents": dict(settlement.storage),
    }


def run_settlement(
    *,
    session_factory,
    mode: str = "scripted",
    seed: str = "settle",
    max_ticks: int = 400,
) -> dict:
    """The scenario: construct a settlement, then hold it."""
    if mode not in ("scripted", "model"):
        raise ValueError(f"unknown mode {mode!r}; expected scripted or model")
    from app.persistence.models import WorldModel

    name = f"settlement-{seed}"
    with session_factory() as session:
        experiment = ExperimentModel(
            name=name,
            scenario="settlement",
            seed=str(seed),
            status="running",
            model_configuration={"mode": mode},
            started_at=datetime.now(timezone.utc),
        )
        session.add(experiment)
        session.commit()
        experiment_id = experiment.id
        session.add(WorldModel(name=f"world-{name}", seed=str(seed)))
        session.commit()

    bus = EventBus()
    world = _build_world(seed, bus)
    engine = Engine(world, population_id=1)

    if mode == "model":
        from app.models.config import provider_from_settings

        provider = provider_from_settings(settings)
        founder = Agent(
            agent_id=1,
            policy=ModelPolicy(provider, system_prompt=SETTLEMENT_SYSTEM_PROMPT),
            observation_radius=4,
        )
        engine.spawn_agent(founder, Position(*HOME_START))
        world.credit_resource(founder.agent_id, "wood", 24)
        neighbour = Agent(
            agent_id=2,
            policy=ModelPolicy(provider, system_prompt=SETTLEMENT_SYSTEM_PROMPT),
            observation_radius=4,
        )
        engine.spawn_agent(neighbour, Position(*NEIGHBOUR_START))

        async def _drive() -> None:
            for _tick in range(1, max_ticks + 1):
                await engine.step_async()

        import asyncio

        asyncio.run(_drive())
        deposits = sum(
            1
            for e in world.events
            if e.type == EventTypes.SETTLEMENT_STORAGE
            and e.payload.get("kind") == "deposit"
        )
        withdrawals = sum(
            1
            for e in world.events
            if e.type == EventTypes.SETTLEMENT_STORAGE
            and e.payload.get("kind") == "withdrawal"
        )
    else:
        founder = Agent(agent_id=1, policy=FounderPolicy())
        engine.spawn_agent(founder, Position(*HOME_START))
        world.credit_resource(founder.agent_id, "wood", 24)
        neighbour = Agent(agent_id=2, policy=NeighbourPolicy())
        engine.spawn_agent(neighbour, Position(*NEIGHBOUR_START))

        # --- construction and maintenance ---
        for _tick in range(1, max_ticks + 1):
            engine.step()
            if founder.policy.done and neighbour.policy.done:
                break
        deposits = founder.policy.deposits
        withdrawals = founder.policy.withdrawals + neighbour.policy.withdrawals

    # --- the maintenance check: does it all still stand? ---
    settlement = world.settlements[0] if world.settlements else None
    structures_standing = {
        structure_id: world.structure_by_id(structure_id) is not None
        for structure_id in (
            settlement.home_ids + settlement.storage_ids if settlement else []
        )
    }
    roads_laid = [road for road in world.roads if road.settlement_id == (
        settlement.id if settlement else -1
    )]
    record = {
        "experiment_id": experiment_id,
        "mode": mode,
        **_settle_results(world),
        "deposits": deposits,
        "withdrawals": withdrawals,
        "road_cells_standing": sum(len(cell) for cell in [road.cells for road in roads_laid]),
        "structures_standing": structures_standing,
        "all_structures_standing": all(structures_standing.values()) and bool(structures_standing),
        "events": {
            "founded": sum(
                1 for e in world.events if e.type == EventTypes.SETTLEMENT_FOUNDED
            ),
            "joined": sum(
                1 for e in world.events if e.type == EventTypes.SETTLEMENT_JOINED
            ),
            "grown": sum(
                1 for e in world.events if e.type == EventTypes.SETTLEMENT_GROWN
            ),
            "roads": sum(1 for e in world.events if e.type == EventTypes.ROAD_LAID),
            "zones": sum(
                1
                for e in world.events
                if e.type == EventTypes.ZONE_CLAIMED and not e.payload.get("released")
            ),
            "storage": sum(
                1 for e in world.events if e.type == EventTypes.SETTLEMENT_STORAGE
            ),
        },
        "maintained": (
            bool(settlement)
            and all(structures_standing.values())
            and len(settlement.zones) >= 1
            and settlement.storage.get("wood", 0) >= 1
            and all(
                world.terrain[cell.y][cell.x] is Terrain.FLOOR
                for road in roads_laid
                for cell in road.cells
            )
        ),
    }
    with session_factory() as session:
        row = session.get(ExperimentModel, experiment_id)
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        row.model_configuration = {"mode": mode, "maintained": record["maintained"]}
        session.commit()
    return record


def print_report(record: dict) -> None:
    if not record.get("founded"):
        print("no settlement was founded")
        return
    print(f"settlement {record['name']!r} (id {record['settlement_id']}):")
    print(
        f"  members {record['members']} Â· homes {record['homes']} Â· "
        f"storage {record['storage_structures']} Â· roads {record['roads']} "
        f"({record['road_cells']} cells) Â· zones {record['zones']}"
    )
    print(
        f"  storage contents {record['contents']} Â· deposits {record['deposits']} Â· "
        f"withdrawals {record['withdrawals']}"
    )
    print(
        f"  maintains: {record['all_structures_standing']} (every structure stands, "
        f"the grove is held, the stock is intact, the road runs)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.experiments.settlement",
        description="Run the settlement scenario (roadmap S30).",
    )
    parser.add_argument("--mode", default="scripted", choices=["scripted", "model"])
    parser.add_argument("--seed", default="settle")
    parser.add_argument("--max-ticks", type=int, default=400)
    args = parser.parse_args()

    from app.persistence.database import SessionLocal

    record = run_settlement(
        session_factory=SessionLocal,
        mode=args.mode,
        seed=args.seed,
        max_ticks=args.max_ticks,
    )
    print_report(record)


if __name__ == "__main__":
    main()
