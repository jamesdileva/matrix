"""S26 — builder vs escapee: the artificial arms race.

The roadmap's checks: prison generated, escape attempt occurs,
successful escape is detected, the builder receives the outcome, and
the next round's rules carry it forward.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.arms_race import (
    CENTER,
    SANDBOX,
    RoundRules,
    _assignments,
    _build_world,
    ring_cells,
    run_arms_race,
    run_round,
)
from app.persistence.database import Base
from app.persistence.models import ExperimentModel


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'arms.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestTheRound:
    def test_a_prison_is_generated(self, session_factory):
        record = run_round(
            session_factory=session_factory,
            round_index=1,
            rules=RoundRules(layers=1),
            seed="gen",
        )

        assert record["blocks_built"] == 16  # the full ring around the cell
        assert record["door_cell"] == [CENTER[0] + 2, CENTER[1]]

    def test_an_escape_attempt_occurs_and_succeeds(self, session_factory):
        record = run_round(
            session_factory=session_factory,
            round_index=1,
            rules=RoundRules(layers=1),
            seed="esc",
        )

        assert record["escaped"] is True
        assert record["escape_tick"] is not None
        assert record["final_position"]["x"] >= SANDBOX[0]

    def test_a_thicker_prison_is_slower_to_escape(self, session_factory):
        thin = run_round(
            session_factory=session_factory,
            round_index=1,
            rules=RoundRules(layers=1),
            seed="thin",
        )
        thick = run_round(
            session_factory=session_factory,
            round_index=2,
            rules=RoundRules(layers=2),
            seed="thick",
        )

        assert thick["blocks_built"] > thin["blocks_built"]
        assert thick["escape_tick"] > thin["escape_tick"]

    def test_the_round_records_its_world(self, session_factory):
        record = run_round(
            session_factory=session_factory,
            round_index=1,
            rules=RoundRules(layers=1),
            seed="rec",
        )

        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "arms_race_round"
            assert experiment.model_configuration["round"] == 1


class TestTheArmsRace:
    def test_rounds_repeat_with_rules_carrying_forward(self, session_factory):
        report = run_arms_race(session_factory=session_factory, rounds=3, seed="race")

        assert len(report["rounds"]) == 3
        assert [r["rules"]["layers"] for r in report["rounds"]] == [1, 2, 3]
        # Every escape thickens the next prison.
        assert report["final_rules"] == {"layers": 4}
        assert report["escapes"] == 3

    def test_the_builder_receives_the_outcome(self, session_factory):
        # The outcome is the input to the next round's rules — that is
        # what "the builder receives the outcome" means here.
        report = run_arms_race(session_factory=session_factory, rounds=2, seed="feedback")

        first, second = report["rounds"]
        assert first["escaped"] is True
        assert second["rules"]["layers"] == first["rules"]["layers"] + 1

    def test_one_round_is_allowed(self, session_factory):
        report = run_arms_race(session_factory=session_factory, rounds=1, seed="solo")
        assert report["final_rules"] == {"layers": 2}  # one escape, one thickening
        assert len(report["rounds"]) == 1

    def test_zero_rounds_rejected(self, session_factory):
        with pytest.raises(ValueError, match="rounds must be"):
            run_arms_race(session_factory=session_factory, rounds=0)


class TestGeometry:
    def test_rings_close(self):
        assert len(ring_cells(*CENTER, 2)) == 16
        assert len(ring_cells(*CENTER, 3)) == 24

    def test_assignments_cover_every_wall_cell_once(self):
        assignments = _assignments(RoundRules(layers=2))
        cells = [cell for cell, _ in assignments]
        assert len(cells) == len(set(cells))
        assert set(cells) == set(ring_cells(*CENTER, 2)) | set(ring_cells(*CENTER, 3))

    def test_assignment_order_builds_inner_rings_first(self):
        # The inner ring's stands are the outer ring's cells; a built
        # block cannot be stood on.
        assignments = _assignments(RoundRules(layers=2))
        inner_first = assignments[0][0] in set(ring_cells(*CENTER, 2))
        assert inner_first

    def test_the_world_has_no_holes_at_the_border(self):
        world = _build_world("geo")
        assert all(world.terrain[0][x] is not None for x in range(world.width))
