"""S38 — world persistence: snapshots, autosave, and the restart path.

The roadmap verification lives here: run a world, kill the server
(process dies, storage survives), bring it back, and the world resumes
exactly where it stood — same tick, same entities, same civilization.
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import WorldModel
from app.persistence.repositories import SnapshotRepository
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.games import LONG_ROAD
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World


def _storage(tmp_path, name="world.db"):
    """Own SQLite file + engine so a test can dispose and 'restart'."""
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _lot(name="round-trip", size=24) -> World:
    # A flat, object-free lot: every coordinate is trustworthy.
    return World(name, size, size, terrain=[[Terrain.FLOOR] * size for _ in range(size)])


def _evolved_world() -> World:
    """A world with every derived system the snapshot must carry."""
    world = _lot()
    engine = Engine(world, population_id=7)
    engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(3, 3))
    engine.spawn_agent(Agent(agent_id=2, policy=WanderPolicy()), Position(3, 4))

    # a structure, then a settlement founded on it
    world.credit_resource(1, "wood", 10)
    built = world.execute_action(
        1, {"action": "build", "direction": "north", "block": "wood_block"}
    )
    assert built.ok, built.reason
    structure_id = built.data["structure_id"]
    settled = world.execute_action(1, {"action": "settle", "name": "hearth"})
    assert settled.ok, settled.reason
    settlement = world.settlement(1)

    # shared storage, a claimed grove, and a road
    settlement.storage["wood"] = 5
    tree = world.place_object(
        "tree", Position(4, 3), properties={"resource": "wood", "quantity": 5}
    )
    claimed = world.execute_action(
        1, {"action": "claim_zone", "resource": "wood", "target": tree.id}
    )
    assert claimed.ok, claimed.reason
    paved = world.execute_action(
        1, {"action": "pave", "cells": [{"x": 2, "y": 3}]}
    )
    assert paved.ok, paved.reason

    # knowledge, a speech and a letter
    world.grant_knowledge(1, ["lashing"])
    world.say(1, "morning")
    world.tell(1, 2, "hello")

    # compute, a population, and a game
    world.set_budget(1, tokens=100, model_calls=5)
    world._spend_budget(1, "tokens", 3)
    world.set_population(1, 7)
    world.set_population(2, 7)
    world.propose_game(None, LONG_ROAD)
    return world


# ----------------------------------------------------------------------
# Round trip: every system survives to_dict -> from_dict
# ----------------------------------------------------------------------


def test_world_round_trip_carries_every_system():
    world = _evolved_world()
    before = world.to_dict()

    restored = World.from_dict(before)
    after = restored.to_dict()

    # Every derived key the snapshot promises is present both times.
    for key in (
        "resources",
        "structures",
        "structure_of",
        "settlements",
        "roads",
        "zones",
        "recipes",
        "patterns",
        "known_recipes",
        "known_patterns",
        "populations",
        "budgets",
        "speeches",
    ):
        assert key in before and key in after, key

    assert after["settlements"] == before["settlements"]
    assert after["roads"] == before["roads"]
    assert after["zones"] == before["zones"]
    assert after["known_recipes"] == before["known_recipes"]
    assert after["structure_of"] == before["structure_of"]
    assert after["populations"] == before["populations"]
    # The budget ledger's spend survives, not just its cap.
    assert after["budgets"]["1"]["tokens"]["spent"] == 3
    assert after["budgets"]["1"]["tokens"]["cap"] == 100

    # The restored world still behaves: a second round trip is stable.
    assert World.from_dict(after).to_dict() == after


def test_restored_settlement_still_holds_its_resources():
    world = _evolved_world()
    restored = World.from_dict(world.to_dict())
    settlement = restored.settlements[0]
    assert settlement.name == "hearth"
    assert settlement.storage == {"wood": 5}
    assert restored.settlement(1).name == "hearth"


# ----------------------------------------------------------------------
# SnapshotRepository
# ----------------------------------------------------------------------


def test_snapshot_repository_stores_and_ranks(tmp_path):
    engine, factory = _storage(tmp_path)
    with Session(engine) as session:
        row = WorldModel(name="repo", seed="repo")
        session.add(row)
        session.commit()
        world_id = row.id

    repo = SnapshotRepository(factory)
    first = repo.save(world_id, {"tick": 10, "seed": "repo"}, kind="manual")
    second = repo.save(world_id, {"tick": 20, "seed": "repo"}, kind="autosave")

    assert repo.latest(world_id).id == second
    assert repo.latest(world_id, kind="manual").id == first
    assert [r.id for r in repo.list(world_id)] == [second, first]
    assert repo.get(first).state["tick"] == 10


def test_snapshot_kinds_are_validated(tmp_path):
    engine, factory = _storage(tmp_path)
    with Session(engine) as session:
        session.add(WorldModel(name="k", seed="k"))
        session.commit()
        world_id = session.query(WorldModel).one().id

    repo = SnapshotRepository(factory)
    try:
        repo.save(world_id, {"tick": 0}, kind="nonsense")
    except ValueError as exc:
        assert "nonsense" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("bad kind should raise")


def test_prune_autosaves_keeps_the_newest(tmp_path):
    engine, factory = _storage(tmp_path)
    with Session(engine) as session:
        session.add(WorldModel(name="p", seed="p"))
        session.commit()
        world_id = session.query(WorldModel).one().id

    repo = SnapshotRepository(factory)
    repo.save(world_id, {"tick": 1}, kind="manual")
    autosaves = [
        repo.save(world_id, {"tick": t}, kind="autosave") for t in (10, 20, 30, 40)
    ]

    dropped = repo.prune_autosaves(world_id, keep=2)
    assert dropped == 2
    remaining = repo.list(world_id)
    assert [r.id for r in remaining if r.kind == "autosave"] == autosaves[-1:-3:-1]
    # manual snapshots are never pruned
    assert any(r.kind == "manual" for r in remaining)


# ----------------------------------------------------------------------
# Autosave cadence
# ----------------------------------------------------------------------


def test_autosave_fires_every_n_ticks(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory, autosave_every=3)
    host = registry.create(seed="auto", width=12, height=12, agents=2, autostart=False)

    async def run():
        for _ in range(7):
            await host.advance_once()

    asyncio.run(run())

    repo = SnapshotRepository(factory)
    ticks = sorted(r.tick for r in repo.list(host.world_id))
    # autosaves at ticks 3 and 6 only (tick 0 is skipped)
    assert ticks == [3, 6]


def test_autosave_disabled_by_default(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)  # autosave_every defaults to 0
    host = registry.create(seed="noauto", width=8, height=8, agents=1, autostart=False)

    async def run():
        for _ in range(5):
            await host.advance_once()

    asyncio.run(run())
    assert SnapshotRepository(factory).list(host.world_id) == []


def test_autosaves_are_pruned_to_the_keep_setting(tmp_path):
    from app.config.settings import settings

    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory, autosave_every=1)
    host = registry.create(seed="pruneme", width=8, height=8, agents=1, autostart=False)

    ticks = settings.autosave_keep + 5

    async def run():
        for _ in range(ticks):
            await host.advance_once()

    asyncio.run(run())

    rows = SnapshotRepository(factory).list(host.world_id)
    assert len(rows) == settings.autosave_keep
    # the newest autosave is retained, and nothing older than the window
    assert max(r.tick for r in rows) == ticks
    assert all(r.kind == "autosave" for r in rows)


# ----------------------------------------------------------------------
# The restart path: run, die, recover
# ----------------------------------------------------------------------


def test_registry_recovers_a_world_from_its_newest_snapshot(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)
    host = registry.create(seed="survivor", width=16, height=16, agents=2, autostart=False)

    async def advance():
        for _ in range(4):
            await host.advance_once()

    asyncio.run(advance())
    host.save("manual")
    saved_tick = host.engine.world.tick
    saved_entities = sorted(host.engine.world.entity_ids)

    # --- the process dies: drop the live registry entirely -------------
    del registry, host
    engine.dispose()

    # --- a fresh process opens the same storage and recovers -----------
    reopened, factory2 = _storage(tmp_path)
    try:
        fresh = WorldRegistry(factory2)
        recovered = fresh.recover(autostart=False)

        assert recovered == [1]
        resumed = fresh.get(1)
        assert resumed.engine.world.tick == saved_tick
        assert sorted(resumed.engine.world.entity_ids) == saved_entities
        assert resumed.brains == "scripted"
    finally:
        reopened.dispose()


def test_recover_returns_nothing_for_a_world_without_snapshots(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)
    registry.create(seed="empty", width=8, height=8, agents=1, autostart=False)

    # no snapshot was ever written
    assert registry.recover(autostart=False) == []


def test_snapshot_excludes_the_unbounded_event_log(tmp_path):
    import json

    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)
    host = registry.create(seed="small", width=16, height=16, agents=2, autostart=False)

    async def tick(count):
        for _ in range(count):
            await host.advance_once()

    asyncio.run(tick(5))
    early = host.snapshot()
    early_size = len(json.dumps(early))
    assert "events" not in early

    asyncio.run(tick(200))
    assert len(host.engine.world.events) > 200  # the log really grew
    late = host.snapshot()
    late_size = len(json.dumps(late))

    # The snapshot carries the world, not its history: doubling+ the
    # event count must not double the snapshot.
    assert "events" not in late
    assert late_size < early_size * 1.5 + 2000


def test_resume_from_a_chosen_snapshot(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)
    host = registry.create(seed="pick", width=12, height=12, agents=2, autostart=False)

    host.save("manual")
    early_tick = host.engine.world.tick

    async def advance():
        for _ in range(3):
            await host.advance_once()

    asyncio.run(advance())
    host.save("manual")
    auto_id = SnapshotRepository(factory).latest(host.world_id).id

    # bring the world back to the chosen (earlier) snapshot
    snapshots = SnapshotRepository(factory).list(host.world_id)
    early_id = snapshots[-1].id

    resumed = asyncio.run(
        registry.resume(host.world_id, early_id, autostart=False)
    )
    assert resumed.engine.world.tick == early_tick

    # resuming a snapshot that is not this world's fails
    try:
        asyncio.run(registry.resume(999, auto_id, autostart=False))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("resume of a foreign snapshot should raise")


def test_recovered_world_keeps_evolving(tmp_path):
    engine, factory = _storage(tmp_path)
    registry = WorldRegistry(factory)
    host = registry.create(seed="living", width=16, height=16, agents=2, autostart=False)
    host.save("manual")
    engine.dispose()

    reopened, factory2 = _storage(tmp_path)
    try:
        fresh = WorldRegistry(factory2)
        fresh.recover(autostart=False)
        resumed = fresh.get(1)

        async def advance():
            before = resumed.engine.world.tick
            for _ in range(3):
                await resumed.advance_once()
            return before

        before = asyncio.run(advance())
        assert resumed.engine.world.tick == before + 3
    finally:
        reopened.dispose()
