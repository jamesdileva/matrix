"""S37 Ã¢â‚¬â€ replay & the time machine.

The verification Ã¢â‚¬â€ "jump from Generation 10,000 back to Generation 0
and inspect intermediate events" Ã¢â‚¬â€ is the deep-lineage class at the
bottom; the classes above it are the machinery that jump rests on.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.replay import router as replay_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.repositories import EventRepository
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import Event, EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.replay import EventReplay
from app.simulation.world import Position, World


class TestTheReplayEngine:
    def _log(self) -> list[Event]:
        world = World("replay", 12, 12)
        engine = Engine(world, population_id=1)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
        events = list(world.events)
        for _ in range(3):
            engine.step()
        return events + list(world.events)

    def test_zero_ticks_is_the_seeded_world(self):
        replay = EventReplay(self._log())
        state = replay.state_at(0)

        assert state.entities[1] == {"x": 2, "y": 2}
        assert state.applied > 0
        assert state.events_seen == state.applied  # everything in this log replays

    def test_moves_are_replayed_in_order(self):
        replay = EventReplay(self._log())
        early = replay.state_at(1)
        later = replay.state_at(3)

        assert early.entities[1] != later.entities[1] or early.tick != later.tick
        assert later.entities[1] != {"x": 2, "y": 2}  # the walker walked

    def test_the_state_is_cached_between_jumps(self):
        replay = EventReplay(self._log())
        first = replay.state_at(2)
        second = replay.state_at(2)

        assert first is second  # a jump back lands on the same reconstruction

    def test_fidelity_is_reported_not_assumed(self):
        log = self._log() + [
            Event(
                id=999,
                tick=4,
                type="SOMETHING_UNKNOWN",
                actor_id=1,
                payload={"message": "from the future"},
            )
        ]
        replay = EventReplay(log)
        state = replay.state_at(4)

        assert state.unapplied["SOMETHING_UNKNOWN"] == 1
        assert state.events_seen == state.applied + 1

    def test_pick_up_and_drop_replay(self):
        world = World("carry", 12, 12)
        engine = Engine(world, population_id=1)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
        tree = world.place_object("tree", Position(2, 3), properties={"quantity": 3})
        world.execute_action(1, {"action": "pick_up", "object_id": tree.id})
        log_up = list(world.events)
        world.execute_action(1, {"action": "drop", "object_id": tree.id})
        log_down = list(world.events)

        carried = EventReplay(log_up).state_at(0)
        assert carried.objects[tree.id]["position"] is None
        assert tree.id in carried.inventories[1]

        dropped = EventReplay(log_down).state_at(0)
        assert dropped.objects[tree.id]["position"] == {"x": 2, "y": 2}
        assert dropped.inventories.get(1, []) == []

    def test_gather_and_build_replay(self):
        world = World("build", 12, 12)
        engine = Engine(world, population_id=1)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
        world.place_object("tree", Position(2, 3), properties={"quantity": 5, "resource": "wood"})
        world.execute_action(1, {"action": "gather", "resource": "wood"})
        world.execute_action(
            1, {"action": "build", "block": "wood_block", "direction": "east"}
        )
        log = list(world.events)

        state = EventReplay(log).state_at(0)
        assert state.resources[1]["wood"] == 0  # gathered one, spent one building
        built = [
            obj for obj in state.objects.values() if obj["type"] == "wood_block"
        ]
        assert len(built) == 1

    def test_births_replay_the_culture_they_carried(self):
        world = World("born", 12, 12)
        engine = Engine(world, population_id=1)
        parent = Agent(agent_id=1, policy=WanderPolicy(), knowledge=["the grove holds wood"])
        engine.spawn_agent(parent, Position(2, 2))
        engine.create_child(1, inheritance={"knowledge": ["the grove holds wood"]})
        log = list(world.events)

        state = EventReplay(log).state_at(0)
        assert 2 in state.entities
        assert state.culture[2]["knowledge"] == ["the grove holds wood"]
        assert state.culture[2]["parent"] == 1

    def test_the_timeline_summarises_the_log(self):
        replay = EventReplay(self._log())
        timeline = replay.timeline()

        assert timeline["events"] > 0
        assert EventTypes.ENTITY_ADDED in timeline["by_type"]
        assert timeline["entities_seen"] >= 1

    def test_the_diff_reports_what_changed(self):
        replay = EventReplay(self._log())
        start = replay.diff(0, 0)
        walked = replay.diff(0, 3)

        assert start["entities_moved"] == {}
        assert walked["from_tick"] == 0 and walked["to_tick"] == 3


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
        application.include_router(replay_router, prefix="/api")
        application.state.worlds = WorldRegistry(
            sessionmaker(bind=engine, expire_on_commit=False)
        )
        with TestClient(application) as test_client:
            yield test_client
        engine.dispose()

    def _create(self, client: TestClient, **payload) -> dict:
        full = {"seed": "s37", "agents": 2, "autostart": False}
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def test_the_timeline_is_readable(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/step")

        body = client.get(f"/api/worlds/{world['id']}/replay/timeline").json()

        assert body["timeline"]["events"] > 0
        assert body["timeline"]["first_tick"] == 0

    def test_the_state_at_a_tick_matches_the_world_shape(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/step")

        state = client.get(f"/api/worlds/{world['id']}/replay/state?tick=0").json()

        assert state["seed"] == "s37"
        assert state["tick"] == 0
        assert state["paused"] is True
        assert state["replay"]["events_seen"] > 0
        # The console renders this exactly as it renders a live world.
        assert set(state) >= {"terrain", "objects", "entities", "width", "height"}

    def test_the_state_jumps_back_and_forth(self, client):
        world = self._create(client)
        for _ in range(3):
            client.post(f"/api/worlds/{world['id']}/step")

        early = client.get(f"/api/worlds/{world['id']}/replay/state?tick=0").json()
        later = client.get(f"/api/worlds/{world['id']}/replay/state?tick=3").json()

        assert early["tick"] == 0
        assert later["tick"] == 3
        assert early["entities"] != later["entities"] or early["replay"]["events_seen"] < later["replay"]["events_seen"]

    def test_events_can_be_filtered_and_jumped_to(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/step")
        page = client.get(
            f"/api/worlds/{world['id']}/replay/events?from_tick=0&to_tick=1&type=ACTION_EXECUTED"
        ).json()

        assert page["count"] >= 1
        event_id = page["events"][0]["id"]
        event = client.get(
            f"/api/worlds/{world['id']}/replay/event/{event_id}"
        ).json()
        assert event["event"]["id"] == event_id
        assert event["event"]["type"] == "ACTION_EXECUTED"

    def test_the_diff_compares_two_ticks(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/step")
        client.post(f"/api/worlds/{world['id']}/step")

        diff = client.get(
            f"/api/worlds/{world['id']}/replay/diff?a=0&b=2"
        ).json()

        assert diff["diff"]["from_tick"] == 0
        assert diff["diff"]["to_tick"] == 2
        assert "resources_changed" in diff["diff"]

    def test_culture_at_a_tick(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/step")

        culture = client.get(
            f"/api/worlds/{world['id']}/replay/culture?tick=1"
        ).json()

        assert culture["tick"] == 1
        assert isinstance(culture["culture"], dict)

    def test_unknown_worlds_are_404s(self, client):
        assert client.get("/api/worlds/999/replay/timeline").status_code == 404

    def test_unknown_events_are_404s(self, client):
        world = self._create(client)

        assert (
            client.get(f"/api/worlds/{world['id']}/replay/event/4242").status_code == 404
        )


class TestTheTimeMachine:
    def test_the_roadmaps_jump(self, tmp_path):
        """Generation 10,000 back to Generation 0, with the history
        between them inspectable."""
        engine = create_engine(
            f"sqlite:///{tmp_path / 'deep.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)

        from app.experiments.lineage import run_lineage_experiment

        report = run_lineage_experiment(
            session_factory=factory,
            mode="full",
            generations=10_000,
            facts=["the river runs east"],
            seed="deep",
            name="deep",
        )
        world_id = _world_of(factory, "world-deep")

        events = EventRepository(factory).load_for_replay(world_id)
        replay = EventReplay(events)

        # The birth at generation 0 and the birth at generation 10,000.
        timeline = replay.timeline()
        assert timeline["generations"] == 10_000
        first, last = timeline["first_tick"], timeline["last_tick"]

        deep_state = replay.state_at(last)
        assert deep_state.culture[10_001]["knowledge"] == ["the river runs east"]
        origin = replay.state_at(first)
        assert 1 in origin.entities  # the founder stands where it was spawned

        # The intermediate history is inspectable: the births between.
        between = replay.events_between(first, last)
        births = [e for e in between if e.type == EventTypes.AGENT_BORN]
        assert len(births) == 10_000
        assert [e.payload["generation"] for e in births[:3]] == [1, 2, 3]

        # A jump to the middle lands on a real reconstruction: the
        # event address is the fine granularity a birth-only lineage
        # needs, since every generation shares one tick.
        middle = replay.state_after(births[5_000].id)
        assert middle.tick == births[5_000].tick
        assert len(middle.entities) == 5_002  # founder plus five thousand children
        # Back to generation 0: the founder's own arrival.
        back_to_zero = replay.state_after(first_birth_id := births[0].id - 2)
        assert back_to_zero.entities.keys() == {1}
        engine.dispose()


def _world_of(session_factory, name: str) -> int:
    from app.persistence.models import WorldModel

    with session_factory() as session:
        row = (
            session.query(WorldModel)
            .filter(WorldModel.name == name)
            .one()
        )
        return row.id
