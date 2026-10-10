"""S23 — the prison sandbox: enclosed, blocked, solvable.

The verification the roadmap asks for: a deterministic scripted solver
can escape — proof the puzzle is solvable. The control (walk east,
solve nothing) cannot, which is what makes the solver's escape
meaningful.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.prison import (
    Prison,
    build_prison,
    run_prison_experiment,
)
from app.persistence.database import Base
from app.persistence.models import EventModel, ExperimentModel
from app.simulation.events import EventTypes
from app.simulation.world import Position, Terrain


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'prison.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestThePuzzle:
    def test_the_room_is_enclosed(self):
        world, [prison] = build_prison()
        # Every wall segment of the room is wall, except the door.
        x0, y0, x1, y1 = prison.room
        dx, dy = prison.door
        wall_cells = [(x, y) for x in range(x0, x1 + 1) for y in (y0, y1)]
        wall_cells += [(x, y) for y in range(y0, y1 + 1) for x in (x0, x1)]
        for x, y in wall_cells:
            if (x, y) != (dx, dy):
                assert world.terrain[y][x] is Terrain.WALL
        assert world.terrain[dy][dx] is Terrain.FLOOR

    def test_the_door_is_blocked_by_a_movable_stone(self):
        world, [prison] = build_prison()
        dx, dy = prison.door
        blocker = world.object_at(Position(dx, dy))
        assert blocker is not None and blocker.type == "stone"
        assert blocker.properties.get("blocks_door") is True

    def test_the_sandbox_is_reachable_only_through_the_door(self):
        world, [prison] = build_prison()
        sx0, sy0, sx1, sy1 = prison.sandbox
        # The sandbox's west border is the room's east wall (with the
        # door gap) — no other opening.
        for y in range(sy0, sy1 + 1):
            cell = world.terrain[y][sx0 - 1]
            if (sx0 - 1, y) != prison.door:
                assert cell is Terrain.WALL


class TestEscape:
    def test_the_scripted_solver_escapes(self, session_factory):
        report = run_prison_experiment(session_factory=session_factory, solver="scripted")

        assert report["escaped"] is True
        assert report["escaped_at_tick"] is not None
        assert report["carrying"]  # the door stone came along
        prison = Prison()
        assert prison.contains(
            prison.sandbox, report["final_position"]["x"], report["final_position"]["y"]
        )

    def test_the_escape_is_recorded_on_the_timeline(self, session_factory):
        report = run_prison_experiment(session_factory=session_factory, solver="scripted")

        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, report["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "prison_escape"
        world_events = report  # the report carries the outcome; the event
        # lands on the world timeline (see the runner's ESCAPED event).
        assert world_events["escaped_at_tick"] >= 1

    def test_the_escape_event_exists_on_the_world(self, session_factory):
        # Drive the run and inspect the world it built via the recorder.
        report = run_prison_experiment(session_factory=session_factory, solver="scripted")
        from app.persistence.models import EventModel

        with Session(session_factory.kw["bind"]) as session:
            escaped = (
                session.query(EventModel)
                .filter_by(type=EventTypes.ESCAPED)
                .all()
            )
        assert len(escaped) == 1
        assert escaped[0].payload["tick"] == report["escaped_at_tick"]

    def test_the_control_cannot_escape(self, session_factory):
        report = run_prison_experiment(
            session_factory=session_factory, solver="walker", ticks=60
        )

        assert report["escaped"] is False
        assert report["carrying"] == []
        # It ends up stuck against the blocked door, inside the room.
        prison = Prison()
        assert prison.contains(
            prison.room, report["final_position"]["x"], report["final_position"]["y"]
        )

    def test_the_solver_is_deterministic(self, session_factory):
        first = run_prison_experiment(session_factory=session_factory, solver="scripted")
        second = run_prison_experiment(session_factory=session_factory, solver="scripted")
        assert first["escaped_at_tick"] == second["escaped_at_tick"]
        assert first["final_position"] == second["final_position"]

    def test_unknown_solver_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown solver"):
            run_prison_experiment(session_factory=session_factory, solver="teleport")
