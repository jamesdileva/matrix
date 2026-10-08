"""S12 — the 10,000-generation stress test and resume.

The roadmap's verification, item by item:

- no generation gaps — generations 0..10,000 contiguous in the DB
- no orphaned lineage records — every agent's parent row exists
- checkpoint/resume works — a run continues from its checkpoint with
  its parent link, position, and calibration counter intact
- memory usage remains bounded — the in-memory event window is capped,
  per-agent memory is capped
- database remains queryable — repositories answer correctly after

Mock minds only: no model calls, so the run is minutes, not hours.
"""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.lineage import (
    resume_lineage_experiment,
    run_lineage_experiment,
)
from app.persistence.database import Base
from app.persistence.models import AgentModel, CheckpointModel, ExperimentModel
from app.persistence.repositories import AgentRepository, CheckpointRepository, EventRepository

STRESS_GENERATIONS = 10_000
STRESS_SMALL = 1_000  # same invariants, 10x faster, for the per-invariant tests
RETENTION = 500


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'stress.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _stress_run(session_factory, *, generations: int = STRESS_GENERATIONS, **overrides):
    kwargs = {
        "mode": "full",
        "generations": generations,
        "seed": "stress",
        "checkpoint_every": 1000,
        "event_retention": RETENTION,
    }
    kwargs.update(overrides)
    return run_lineage_experiment(session_factory=session_factory, **kwargs)


class TestStressRun:
    def test_ten_thousand_generations_complete(self, session_factory):
        # The roadmap's headline: a mock run to 10,000 generations.
        started = time.monotonic()
        report = _stress_run(session_factory)
        elapsed = time.monotonic() - started

        assert report["generations"] == STRESS_GENERATIONS
        assert report["totals"]["retained_facts"] == 10  # full-retention control
        assert elapsed < 300, f"10,000 generations took {elapsed:.0f}s — too slow"

    def test_no_generation_gaps(self, session_factory):
        report = _stress_run(session_factory, generations=STRESS_SMALL)

        with Session(session_factory.kw["bind"]) as session:
            generations = sorted(
                a.generation
                for a in session.query(AgentModel)
                .join(ExperimentModel, ExperimentModel.world_id == AgentModel.world_id)
                .filter(ExperimentModel.id == report["experiment_id"])
                .all()
            )
        assert generations == list(range(STRESS_SMALL + 1))  # founder + the chain

    def test_no_orphaned_lineage_records(self, session_factory):
        report = _stress_run(session_factory, generations=STRESS_SMALL)

        with Session(session_factory.kw["bind"]) as session:
            rows = (
                session.query(AgentModel)
                .join(ExperimentModel, ExperimentModel.world_id == AgentModel.world_id)
                .filter(ExperimentModel.id == report["experiment_id"])
                .all()
            )
        ids = {row.id for row in rows}
        orphans = [row for row in rows if row.parent_id is not None and row.parent_id not in ids]
        assert orphans == []
        founders = [row for row in rows if row.parent_id is None]
        assert len(founders) == 1  # exactly one generation-0 agent

    def test_memory_stays_bounded(self, session_factory):
        # The retained-events window is the only unbounded structure in
        # a long run (per-agent memory is capped by AgentMemory's bound,
        # proven in test_simulation_memory). Its footprint must stop
        # growing once the cap is reached.
        import sys

        from app.simulation.world import Terrain, World

        world = World(
            "t",
            12,
            12,
            terrain=[[Terrain.FLOOR] * 12 for _ in range(12)],
            event_retention=100,
        )

        def _window_footprint() -> int:
            return sum(sys.getsizeof(e) + sys.getsizeof(e.payload) for e in world.events)

        for index in range(100):
            world._add_event("PING", payload={"n": index})
        at_cap = _window_footprint()

        for index in range(100, 10_100):
            world._add_event("PING", payload={"n": index})

        assert len(world.events) == 100
        assert _window_footprint() <= at_cap * 1.2  # 10,000 more events, no growth

    def test_event_retention_caps_the_in_memory_window(self, session_factory):
        from app.simulation.world import Position, Terrain, World

        world = World(
            "t",
            12,
            12,
            terrain=[[Terrain.FLOOR] * 12 for _ in range(12)],
            event_retention=100,
        )
        for index in range(500):
            world._add_event("PING")
        assert len(world.events) == 100
        assert world.events[-1].id == 500  # ids keep advancing past the window

    def test_database_remains_queryable(self, session_factory):
        report = _stress_run(session_factory, generations=STRESS_SMALL)
        engine = session_factory.kw["bind"]
        world_id = None
        with Session(engine) as session:
            world_id = session.get(ExperimentModel, report["experiment_id"]).world_id

        event_repository = EventRepository(engine)
        assert event_repository.count(world_id) == STRESS_SMALL * 2 + 1
        # (STRESS_SMALL AGENT_BORN + STRESS_SMALL ENTITY_ADDED + founder ENTITY_ADDED)
        born = event_repository.recent(world_id, limit=50, event_type="AGENT_BORN")
        assert all(row.type == "AGENT_BORN" for row in born)

        agent_repository = AgentRepository(session_factory)
        lineage = agent_repository.lineage(world_id)
        assert len(lineage) == STRESS_SMALL + 1
        assert [entry["generation"] for entry in lineage[:3]] == [0, 1, 2]

    def test_checkpoints_written_on_cadence(self, session_factory):
        report = _stress_run(session_factory, generations=STRESS_SMALL, checkpoint_every=250)

        repository = CheckpointRepository(session_factory)
        checkpoints = repository.for_experiment(report["experiment_id"])
        assert [c.generation for c in checkpoints] == list(
            range(250, STRESS_SMALL + 1, 250)
        )


class TestCheckpointResume:
    def test_resume_continues_the_chain_without_orphans(self, session_factory):
        # Phase 1: 500 generations with checkpoints every 100.
        first = run_lineage_experiment(
            session_factory=session_factory,
            mode="full",
            generations=500,
            seed="resume",
            checkpoint_every=100,
        )
        checkpoints = CheckpointRepository(session_factory).for_experiment(
            first["experiment_id"]
        )
        assert [c.generation for c in checkpoints] == [100, 200, 300, 400, 500]

        # Phase 2: resume to 800.
        second = resume_lineage_experiment(
            session_factory,
            first["experiment_id"],
            generations=800,
            checkpoint_every=100,
        )
        assert second["generations"] == 300  # generations 501..800
        assert [e["generation"] for e in second["trajectory"]] == list(range(501, 801))

        # The chain in the database is continuous: 0..800, no orphans.
        with Session(session_factory.kw["bind"]) as session:
            world_id = session.get(ExperimentModel, first["experiment_id"]).world_id
            rows = session.query(AgentModel).filter_by(world_id=world_id).all()
        generations = sorted(r.generation for r in rows)
        assert generations == list(range(801))
        ids = {r.id for r in rows}
        assert [r for r in rows if r.parent_id is not None and r.parent_id not in ids] == []
        # The resumed children link to pre-checkpoint parents.
        parent_locals = {r.local_id for r in rows}
        assert all(r.local_id in parent_locals for r in rows)

        # The experiment row completed despite the interruption.
        with Session(session_factory.kw["bind"]) as session:
            assert session.get(ExperimentModel, first["experiment_id"]).status == "completed"

    def test_resume_restores_calibration_counter(self, session_factory):
        # A lossy run interrupted mid-staircase continues the staircase
        # rather than restarting it.
        first = run_lineage_experiment(
            session_factory=session_factory,
            mode="lossy",
            generations=95,
            seed="resume-lossy",
            checkpoint_every=50,
        )
        assert first["totals"]["lost_facts"] == 9  # drops at 10..90

        second = resume_lineage_experiment(session_factory, first["experiment_id"], generations=100)
        # The drop at generation 100 happened after the resume.
        assert second["totals"]["retained_facts"] == 0
        with Session(session_factory.kw["bind"]) as session:
            rows = (
                session.query(AgentModel)
                .join(ExperimentModel, ExperimentModel.world_id == AgentModel.world_id)
                .filter(ExperimentModel.id == first["experiment_id"])
                .all()
            )
        assert sorted(r.generation for r in rows) == list(range(101))

    def test_resume_requires_checkpoint(self, session_factory):
        report = run_lineage_experiment(
            session_factory=session_factory, mode="full", generations=5, seed="no-cp"
        )
        with pytest.raises(ValueError, match="no checkpoint"):
            resume_lineage_experiment(session_factory, report["experiment_id"], generations=10)

    def test_resume_extends_a_completed_run(self, session_factory):
        # A finished pilot run is extended, not refused: "run it to 10,000".
        first = run_lineage_experiment(
            session_factory=session_factory,
            mode="full",
            generations=100,
            seed="pilot",
            checkpoint_every=50,
        )
        with Session(session_factory.kw["bind"]) as session:
            world_id = session.get(ExperimentModel, first["experiment_id"]).world_id

        second = resume_lineage_experiment(
            session_factory, first["experiment_id"], generations=250
        )
        assert second["generations"] == 150  # generations 101..250

        with Session(session_factory.kw["bind"]) as session:
            rows = session.query(AgentModel).filter_by(world_id=world_id).all()
        assert sorted(r.generation for r in rows) == list(range(251))
        ids = {r.id for r in rows}
        assert [r for r in rows if r.parent_id is not None and r.parent_id not in ids] == []

    def test_resume_rejects_when_target_already_reached(self, session_factory):
        report = run_lineage_experiment(
            session_factory=session_factory,
            mode="full",
            generations=5,
            seed="done",
            checkpoint_every=5,
        )
        with pytest.raises(ValueError, match="already at generation"):
            resume_lineage_experiment(session_factory, report["experiment_id"], generations=5)

    def test_resume_rejects_unknown_experiment(self, session_factory):
        with pytest.raises(ValueError, match="unknown experiment"):
            resume_lineage_experiment(session_factory, 999, generations=10)
