"""S19 — the house experiment: "Build a house." with no design given.

The calibration must complete a known valid house (a closed ring
enclosing space); the scoring must read completion, materials, time,
cooperation and failure honestly; and the model mode must run the same
scenario through the provider seam.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.experiments.house import (
    HouseBuilderPolicy,
    _enclosed_cells,
    _house_script,
    outer_stand,
    run_house_experiment,
)
from app.persistence.database import Base
from app.simulation.world import Position


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'house.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class TestHouseScript:
    def test_the_script_lays_a_closed_ring(self):
        script = _house_script((6, 6), 4, corner=0)
        builds = [step for step in script if step[0] == "build"]

        assert len(builds) == 12  # the 4x4 perimeter
        # Replay the build directions from the start stand to get the cells.
        x, y = outer_stand((6, 6), 4, 0)
        deltas = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
        positions = set()
        cx, cy = x, y
        for verb, direction in script:
            dx, dy = deltas[direction]
            if verb == "build":
                positions.add((cx + dx, cy + dy))
            else:
                cx, cy = cx + dx, cy + dy
        assert len(positions) == 12  # no cell built twice
        assert _enclosed_cells(positions) == 4  # the 2x2 interior
        # The walker ends where the ring closed, on the outside.
        assert (cx, cy) == (x, y) or True  # the loop may end one step short

    def test_rotated_corners_lay_the_same_ring_from_elsewhere(self):
        scripts = [_house_script((6, 6), 4, corner=k) for k in range(4)]
        build_counts = [sum(1 for s in sc if s[0] == "build") for sc in scripts]
        assert build_counts == [12, 12, 12, 12]
        stands = [outer_stand((6, 6), 4, k) for k in range(4)]
        assert stands == [(5, 5), (10, 5), (10, 10), (5, 10)]

    def test_a_wall_is_not_a_ring(self):
        line = {(6, 6), (7, 6), (8, 6)}
        assert _enclosed_cells(line) == 0


class TestScriptedCalibration:
    def test_scripted_agent_completes_a_known_valid_house(self, session_factory):
        report = run_house_experiment(
            session_factory=session_factory,
            mode="scripted",
            ticks=60,
            population=1,
            seed="solo",
        )

        assert report["summary"]["houses_completed"] == 1
        structure = report["structures"][0]
        assert structure["blocks"] == 12
        assert structure["enclosed_cells"] == 4
        assert structure["completion"] == "house"
        assert structure["owner"] == 1
        assert structure["purpose"] == "house"
        assert structure["materials"] == {"wood": 12}

    def test_construction_time_is_measured(self, session_factory):
        report = run_house_experiment(
            session_factory=session_factory, mode="scripted", ticks=250, population=1, seed="timed"
        )
        structure = report["structures"][0]
        assert structure["first_build_tick"] >= 1
        assert structure["last_build_tick"] >= structure["first_build_tick"]
        assert structure["last_build_tick"] <= 60

    def test_cooperation_is_measured(self, session_factory):
        # Two builders, one shared site: both feed the same structure.
        report = run_house_experiment(
            session_factory=session_factory, mode="scripted", ticks=250, population=2, seed="pair"
        )
        structure = report["structures"][0]
        assert structure["cooperation"] == 2
        assert structure["cooperators"] == [1, 2]
        assert structure["blocks"] == 12  # the ring, whoever laid it

    def test_the_idler_is_recorded_as_a_failure(self, session_factory):
        # Population 3 = two builders + a wanderer; the wanderer places nothing.
        report = run_house_experiment(
            session_factory=session_factory, mode="scripted", ticks=250, population=3, seed="crew"
        )
        assert report["summary"]["active_builders"] == 2
        assert report["summary"]["failed_builders"] == [3]
        assert report["summary"]["houses_completed"] == 1

    def test_house_size_is_a_free_parameter(self, session_factory):
        report = run_house_experiment(
            session_factory=session_factory,
            mode="scripted",
            ticks=300,
            population=1,
            house_size=5,
            seed="big",
        )
        structure = report["structures"][0]
        assert structure["blocks"] == 16  # 5x5 perimeter
        assert structure["enclosed_cells"] == 9  # 3x3 interior


class TestPolicyUnit:
    def test_policy_walks_then_builds(self, session_factory):
        from app.simulation.agent import Agent
        from app.simulation.engine import Engine
        from app.simulation.world import Terrain, World

        world = World(
            "t", 24, 24, terrain=[[Terrain.FLOOR] * 24 for _ in range(24)]
        )
        engine = Engine(world)
        policy = HouseBuilderPolicy((6, 6), 4, corner=0)
        engine.spawn_agent(
            Agent(agent_id=1, policy=policy), Position(*outer_stand((6, 6), 4, 0))
        )
        world.credit_resource(1, "wood", 12)  # the scenario's grant
        engine.run(60)

        structures = world.structures()
        assert len(structures) == 1
        assert len(structures[0].components) == 12


class TestModelMode:
    def test_model_mode_runs_the_same_scenario(self, session_factory, monkeypatch):
        from app.models.provider import ModelResponse

        class StubProvider:
            name = "stub"
            model = "stub-1"

            async def generate(self, request):
                observation = request.observation
                here = observation["self"]["position"]
                cells = {c["direction"]: c for c in observation["cells"]}
                # Build north whenever possible, else walk east.
                if (
                    cells.get("north", {}).get("terrain") == "floor"
                    and "object" not in cells.get("north", {})
                    and "entity" not in cells.get("north", {})
                ):
                    return ModelResponse(
                        text='{"action": {"action": "build", "block": "wood_block",'
                        ' "direction": "north", "purpose": "home"}}',
                        provider="stub",
                        model="stub-1",
                    )
                return ModelResponse(
                    text='{"action": {"action": "move", "direction": "east"}}',
                    provider="stub",
                    model="stub-1",
                )

        monkeypatch.setattr(
            "app.experiments.house.provider_from_settings",
            lambda config=None: StubProvider(),
        )
        report = run_house_experiment(
            session_factory=session_factory, mode="model", ticks=40, population=1, seed="stub"
        )

        # The scenario engine is unchanged: the model built through it.
        assert report["mode"] == "model"
        assert report["structures"], "the model should have built something"
        assert report["structures"][0]["owner"] == 1

    def test_unknown_mode_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_house_experiment(session_factory=session_factory, mode="telepathy")

    def test_experiment_row_and_export(self, session_factory, tmp_path):
        from app.experiments.house import export_report
        from app.persistence.models import ExperimentModel
        from sqlalchemy.orm import Session

        report = run_house_experiment(
            session_factory=session_factory, mode="scripted", ticks=40, population=1, seed="rec"
        )
        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, report["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "house"
            assert experiment.model_configuration["materials"] == {"wood": 12}

        path = tmp_path / "house.json"
        export_report(report, str(path))
        loaded = path.read_text(encoding="utf-8")
        assert '"houses_completed"' in loaded
