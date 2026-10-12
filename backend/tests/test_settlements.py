"""S30 â€” settlements: homes, shared storage, roads, identity, zones.

The roadmap's verification â€” "a population can construct and maintain
a small settlement" â€” is the last class here; the classes before it
are the mechanics it rests on.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.experiments.settlement import run_settlement
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World


def _lot() -> World:
    # A flat, object-free lot: every coordinate in these tests is
    # trustworthy, the way the experiment's scenario lays its own.
    return World(
        "settle-test",
        24,
        24,
        terrain=[[Terrain.FLOOR] * 24 for _ in range(24)],
    )


def _world_with(*agent_spots: tuple[int, int]) -> tuple[World, Engine]:
    world = _lot()
    engine = Engine(world, population_id=1)
    for index, spot in enumerate(agent_spots, start=1):
        engine.spawn_agent(Agent(agent_id=index, policy=WanderPolicy()), Position(*spot))
    return world, engine


def _free_spot(world: World, x: int, y: int) -> Position:
    """The first free floor cell at or after (x, y), row-major."""
    for row in range(y, world.height - 1):
        for column in range(x if row == y else 1, world.width - 1):
            cell = Position(column, row)
            if (
                world.is_floor(cell)
                and world.object_at(cell) is None
                and world.entity_at(cell) is None
            ):
                return cell
    raise AssertionError("no free spot on the lot")


def _place_tree(world: World, x: int, y: int, quantity: int = 5):
    """A tree on a free cell, adjacent-ready for the tests' gatherers."""
    spot = _free_spot(world, x, y)
    return world.place_object(
        "tree", spot, properties={"quantity": quantity, "resource": "wood"}
    )


def _structure_from(
    world: World, engine: Engine, actor_id: int, at: tuple[int, int], purpose: str | None = None
) -> int:
    """Raise three contiguous blocks as one structure; return its id.

    The builder walks as it goes — build north, step east, build west
    twice — so the blocks touch and group into a single structure (S18
    adjacency), which is what a home is.
    """
    world.credit_resource(actor_id, "wood", 3)
    payload = {"action": "build", "block": "wood_block"}
    if purpose:
        payload["purpose"] = purpose
    for verb, direction in (
        ("build", "north"),
        ("move", "east"),
        ("build", "west"),
        ("move", "east"),
        ("build", "west"),
    ):
        action = payload if verb == "build" else {"action": "move"}
        result = world.execute_action(actor_id, {**action, "direction": direction})
        assert result.ok, (verb, direction, result.reason)
    structures = world.structures()
    assert len(structures[-1].components) == 3, "the blocks should be one structure"
    return structures[-1].id


class TestFounding:
    def test_a_settlement_has_a_name_a_founder_and_a_home(self):
        world, engine = _world_with((3, 3))
        structure_id = _structure_from(world, engine, 1, (3, 4))

        result = world.execute_action(
            1, {"action": "settle", "name": "First Hollow", "structure": structure_id}
        )

        assert result.ok
        settlement = world.settlement(1)
        assert settlement.name == "First Hollow"
        assert settlement.founder_id == 1
        assert settlement.role_of(1) == "founder"
        assert settlement.home_ids == [structure_id]
        assert world.settlement_of(1) is settlement
        events = [e for e in world.events if e.type == EventTypes.SETTLEMENT_FOUNDED]
        assert len(events) == 1
        assert events[0].payload["name"] == "First Hollow"

    def test_settling_on_the_structure_beside_you_needs_no_id(self):
        world, engine = _world_with((3, 3))
        _structure_from(world, engine, 1, (3, 4))

        result = world.execute_action(1, {"action": "settle", "name": "Beside You"})

        assert result.ok
        assert result.data["name"] == "Beside You"

    def test_a_name_is_required_and_names_are_unique(self):
        world, engine = _world_with((3, 3), (8, 8))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Hollow", "structure": structure_id})

        unnamed = world.execute_action(2, {"action": "settle", "name": "  "})
        assert unnamed.reason == "invalid_name"

        # A second settlement needs its own structure â€” and its own name.
        other = _structure_from(world, engine, 2, (8, 8))
        duplicate = world.execute_action(
            2, {"action": "settle", "name": "Hollow", "structure": other}
        )
        assert duplicate.reason == "cannot_settle"
        fresh = world.execute_action(
            2, {"action": "settle", "name": "Elsewhere", "structure": other}
        )
        assert fresh.ok
        assert len(world.settlements) == 2

    def test_one_people_one_settlement(self):
        world, engine = _world_with((3, 3))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Home", "structure": structure_id})

        again = world.execute_action(
            1, {"action": "settle", "name": "Second", "structure": structure_id}
        )

        assert again.reason == "cannot_settle"


class TestMembership:
    def test_your_people_join(self):
        world, engine = _world_with((3, 3), (3, 8))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Kin", "structure": structure_id})

        joined = world.execute_action(2, {"action": "join_settlement", "settlement_id": 1})

        assert joined.ok
        assert world.settlement_of(2) is world.settlement_of(1)

    def test_other_peoples_are_refused(self):
        world, engine = _world_with((3, 3), (3, 8))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Kin", "structure": structure_id})
        world.set_population(1, 1)
        world.set_population(2, 2)

        refused = world.execute_action(2, {"action": "join_settlement", "settlement_id": 1})

        assert refused.reason == "cannot_join"
        assert world.settlement_of(2) is None

    def test_joining_twice_or_nowhere_is_a_clean_refusal(self):
        world, engine = _world_with((3, 3), (3, 8))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Kin", "structure": structure_id})

        assert (
            world.execute_action(1, {"action": "join_settlement", "settlement_id": 1}).reason
            == "cannot_join"
        )
        assert (
            world.execute_action(2, {"action": "join_settlement", "settlement_id": 9}).reason
            == "cannot_join"
        )


class _Storehouse:
    """A settlement with a home and an adopted storehouse, and both
    members standing beside the storehouse."""

    def __init__(self) -> None:
        world, engine = _world_with((3, 3), (20, 3))
        self.world = world
        self.engine = engine
        self.home_id = _structure_from(world, engine, 1, (3, 4), purpose="home")
        world.execute_action(
            1, {"action": "settle", "name": "Store", "structure": self.home_id}
        )
        # The storehouse stands apart from the home but inside the
        # extent; the builder walks east to its site first.
        world.execute_action(1, {"action": "move", "direction": "east"})
        world.execute_action(1, {"action": "move", "direction": "east"})
        self.storage_id = _structure_from(world, engine, 1, (7, 3), purpose="storage")
        # A member building inside the extent grows the settlement on
        # the spot: the storehouse is adopted without being asked.
        settlement = world.settlement(1)
        assert self.storage_id in settlement.storage_ids
        world.execute_action(2, {"action": "join_settlement", "settlement_id": 1})
        # Both members stand beside the storehouse.
        world.remove_entity(1)
        world.add_entity(1, Position(9, 3))
        world.remove_entity(2)
        world.add_entity(2, Position(7, 4))
        self.founder, self.neighbour = engine.agents[0], engine.agents[1]


def _storehouse() -> _Storehouse:
    return _Storehouse()


class TestStorage:
    def test_members_bank_and_draw(self):
        scenario = _storehouse()
        world = scenario.world
        world.credit_resource(1, "wood", 4)

        deposited = world.execute_action(
            1, {"action": "deposit", "resource": "wood", "amount": 3}
        )

        assert deposited.ok
        assert deposited.data["balance"] == {"wood": 3}
        assert world.resource_count(1, "wood") == 1  # the grant minus three
        events = [e for e in world.events if e.type == EventTypes.SETTLEMENT_STORAGE]
        assert events[-1].payload["kind"] == "deposit"

    def test_the_shared_ledger_is_the_settlements(self):
        scenario = _storehouse()
        world = scenario.world
        world.credit_resource(1, "wood", 3)
        world.execute_action(1, {"action": "deposit", "resource": "wood", "amount": 3})

        # The neighbour draws from it: shared means shared.
        drawn = world.execute_action(
            2, {"action": "withdraw", "resource": "wood", "amount": 2}
        )

        assert drawn.ok
        assert drawn.data["balance"] == {"wood": 1}
        assert world.resource_count(2, "wood") == 2

    def test_you_cannot_bank_what_you_do_not_carry(self):
        scenario = _storehouse()
        world = scenario.world

        refused = world.execute_action(
            1, {"action": "deposit", "resource": "wood", "amount": 1}
        )

        assert refused.reason == "refused"
        assert "carries 0" in refused.data["detail"]

    def test_you_cannot_draw_more_than_stands(self):
        scenario = _storehouse()
        world = scenario.world
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "deposit", "resource": "wood", "amount": 2})

        refused = world.execute_action(
            2, {"action": "withdraw", "resource": "wood", "amount": 5}
        )

        assert refused.reason == "refused"


class TestZones:
    def _grove(self, *spots: tuple[int, int]):
        world, engine = _world_with(*spots)
        structure_id = _structure_from(world, engine, 1, spots[0])
        world.execute_action(1, {"action": "settle", "name": "Grove", "structure": structure_id})
        return world, engine

    def test_a_claimed_grove_refuses_outsiders(self):
        world, engine = self._grove((3, 3), (6, 4))
        # The grove stands beside the founder (who ends at (5, 3)).
        tree = _place_tree(world, 5, 4)

        claimed = world.execute_action(
            1, {"action": "claim_zone", "resource": "wood", "target": tree.id}
        )

        assert claimed.ok
        assert world.zone_claimer(tree.id) == 1

        outsider = world.execute_action(2, {"action": "gather", "resource": "wood"})

        assert outsider.reason == "claimed_by"
        assert outsider.data["settlement_id"] == 1
        assert tree.properties["quantity"] == 5  # nothing was taken

    def test_members_gather_their_own_grove_freely(self):
        world, engine = self._grove((3, 3), (6, 4))
        tree = _place_tree(world, 5, 4)
        world.execute_action(1, {"action": "claim_zone", "resource": "wood", "target": tree.id})
        world.execute_action(2, {"action": "join_settlement", "settlement_id": 1})

        gathered = world.execute_action(2, {"action": "gather", "resource": "wood"})

        assert gathered.ok
        assert gathered.data["amount"] == 1

    def test_claims_can_be_released(self):
        world, engine = self._grove((3, 3), (6, 4))
        tree = _place_tree(world, 5, 4)
        world.execute_action(1, {"action": "claim_zone", "resource": "wood", "target": tree.id})

        released = world.execute_action(1, {"action": "release_zone", "target": tree.id})

        assert released.ok
        assert world.zone_claimer(tree.id) is None
        assert world.execute_action(2, {"action": "gather", "resource": "wood"}).ok

    def test_only_holders_claim(self):
        world, engine = self._grove((3, 3), (8, 8))
        tree = _place_tree(world, 8, 7)  # beside the would-be claimant

        claimed = world.execute_action(
            2,
            {
                "action": "claim_zone",
                "resource": "wood",
                "target": tree.id,
                "settlement_id": 1,
            },
        )

        assert claimed.reason == "not_a_member"


class TestRoads:
    def _settled(self):
        world, engine = _world_with((3, 3))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Roads", "structure": structure_id})
        return world, engine

    def test_a_road_is_walkable_and_recorded(self):
        world, engine = self._settled()

        # The builder stands at (5, 3) after raising its home; the road
        # runs north from there.
        paved = world.execute_action(
            1,
            {"action": "pave", "cells": [{"x": 5, "y": 2}, {"x": 5, "y": 1}]},
        )

        assert paved.ok
        roads = [r for r in world.roads if r.settlement_id == 1]
        assert len(roads) == 1
        assert len(roads[0].cells) == 2
        # A road blocks nothing: an agent walks straight over it.
        engine.spawn_agent(Agent(agent_id=9, policy=WanderPolicy()), Position(6, 1))
        assert world.execute_action(9, {"action": "move", "direction": "west"}).ok  # onto the road
        assert world.execute_action(9, {"action": "move", "direction": "west"}).ok
        events = [e for e in world.events if e.type == EventTypes.ROAD_LAID]
        assert len(events) == 1

    def test_roads_join_into_one_path(self):
        world, engine = self._settled()
        # Lay one cell, walk onto it, lay the next beside it: the two
        # paves join into a single road, not a scatter of paths.
        world.execute_action(1, {"action": "pave", "cells": [{"x": 5, "y": 2}]})
        world.execute_action(1, {"action": "move", "direction": "north"})
        world.execute_action(1, {"action": "pave", "cells": [{"x": 5, "y": 1}]})

        roads = [r for r in world.roads if r.settlement_id == 1]
        assert len(roads) == 1
        assert len(roads[0].cells) == 2
        events = [e for e in world.events if e.type == EventTypes.ROAD_LAID]
        assert len(events) == 2

    def test_roads_stay_inside_the_settlement(self):
        world, _engine = self._settled()

        far = world.execute_action(
            1, {"action": "pave", "cells": [{"x": 20, "y": 3}, {"x": 21, "y": 3}]}
        )

        assert far.reason == "refused"
        assert world.roads == []


class TestAdoption:
    def test_a_member_building_inside_the_extent_grows_the_settlement(self):
        world, engine = _world_with((3, 3))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Village", "structure": structure_id})
        # Build again, inside the extent (but not on a block): the walk
        # to a fresh site is part of the settlement growing.
        world.remove_entity(1)
        world.add_entity(1, Position(7, 7))
        _structure_from(world, engine, 1, (7, 7))

        settlement = world.settlement(1)
        assert len(settlement.home_ids) == 2
        grown = [e for e in world.events if e.type == EventTypes.SETTLEMENT_GROWN]
        assert len(grown) == 1
        assert grown[0].payload["kind"] == "home"

    def test_a_storehouse_adoption_is_classified(self):
        world, engine = _world_with((3, 3))
        home_id = _structure_from(world, engine, 1, (3, 4), purpose="home")
        world.execute_action(1, {"action": "settle", "name": "Village", "structure": home_id})
        world.remove_entity(1)
        world.add_entity(1, Position(7, 7))
        storage_id = _structure_from(world, engine, 1, (7, 7), purpose="storage")

        settlement = world.settlement(1)
        assert settlement.home_ids == [home_id]
        assert settlement.storage_ids == [storage_id]


class TestObservation:
    def test_a_member_sees_its_settlement(self):
        world, engine = _world_with((3, 3), (3, 8))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Seen", "structure": structure_id})
        world.execute_action(2, {"action": "join_settlement", "settlement_id": 1})

        view = engine.agents[0].observe()["settlement"]

        assert view["name"] == "Seen"
        assert view["role"] == "founder"
        assert view["members"] == [1, 2]
        assert view["contents"] == {}

    def test_an_outsider_sees_nothing(self):
        world, engine = _world_with((3, 3), (20, 20))
        structure_id = _structure_from(world, engine, 1, (3, 4))
        world.execute_action(1, {"action": "settle", "name": "Seen", "structure": structure_id})

        assert engine.agents[1].observe()["settlement"] is None


class TestTheExperiment:
    @pytest.fixture()
    def session_factory(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'settle.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()

    def test_a_settlement_is_constructed_and_maintained(self, session_factory):
        record = run_settlement(session_factory=session_factory, seed="verify")

        assert record["founded"] is True
        assert record["name"] == "First Hollow"
        assert record["members"] == [1, 2]  # the founder and the neighbour
        assert record["homes"] == 2  # both homes, the second adopted on build
        assert record["storage_structures"] == 1
        assert record["roads"] == 1
        assert record["road_cells"] == 5
        assert record["zones"] == 1
        assert record["contents"]["wood"] >= 1  # the stock survives
        assert record["events"]["founded"] == 1
        assert record["events"]["joined"] == 1
        assert record["events"]["grown"] >= 1
        assert record["events"]["roads"] == 1
        assert record["events"]["zones"] == 1
        assert record["all_structures_standing"] is True
        assert record["maintained"] is True

    def test_the_run_is_deterministic(self, session_factory):
        first = run_settlement(session_factory=session_factory, seed="same")
        second = run_settlement(session_factory=session_factory, seed="same")

        assert first["maintained"] is True
        assert first["maintained"] == second["maintained"]
        assert first["road_cells"] == second["road_cells"]
        assert first["contents"] == second["contents"]

    def test_unknown_modes_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_settlement(session_factory=session_factory, mode="shout")

    def test_model_mode_runs_the_same_scenario(self, session_factory):
        # Through the mock seam: same lot, same measures, model minds.
        record = run_settlement(
            session_factory=session_factory, mode="model", seed="mock-minds", max_ticks=3
        )

        assert record["mode"] == "model"
        assert "maintained" in record
        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "settlement"

    def test_the_experiment_row_completes(self, session_factory):
        record = run_settlement(session_factory=session_factory, seed="row")

        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "settlement"
            assert experiment.model_configuration["maintained"] is True


class TestTheAPI:
    @pytest.fixture()
    def client(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'api.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        application = FastAPI()
        application.include_router(health_router, prefix="/api")
        application.include_router(worlds_router, prefix="/api")
        application.state.worlds = WorldRegistry(
            sessionmaker(bind=engine, expire_on_commit=False)
        )
        with TestClient(application) as test_client:
            yield test_client
        engine.dispose()

    def _create(self, client: TestClient, **payload) -> dict:
        full = {"seed": "s30", "agents": 2, "autostart": False}
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def test_settlements_live_in_the_worlds_route(self, client):
        world = self._create(client)

        body = client.get(f"/api/worlds/{world['id']}/settlements").json()

        assert body["settlements"] == []

    def test_a_settlement_founded_through_the_route(self, client):
        world = self._create(
            client,
            populations=[{"name": "builders", "members": 1, "stipend": {"wood": 4}}],
        )
        # The spawn scans from the corner, so north is the border wall:
        # build east and south from the founder's own cell.
        for direction in ("east", "south"):
            response = client.post(
                f"/api/worlds/{world['id']}/actions",
                json={
                    "agent_id": 1,
                    "action": {
                        "action": "build",
                        "block": "wood_block",
                        "direction": direction,
                        "purpose": "home",
                    },
                },
            )
            assert response.json()["ok"] is True

        founded = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "settle", "name": "First Hollow"}},
        )

        assert founded.json()["ok"] is True
        listing = client.get(f"/api/worlds/{world['id']}/settlements").json()
        settlement = listing["settlements"][0]
        assert settlement["name"] == "First Hollow"
        assert settlement["homes"] == 1
        assert settlement["members_with_roles"] == [{"agent_id": 1, "role": "founder"}]

        detail = client.get(
            f"/api/worlds/{world['id']}/settlements/{settlement['id']}"
        ).json()
        assert detail["settlement"]["founder_id"] == 1

    def test_unknown_settlement_is_a_404(self, client):
        world = self._create(client)

        assert client.get(f"/api/worlds/{world['id']}/settlements/999").status_code == 404
