"""S28 — communication networks: routing, the three new actions,
and the rumor experiment.

The roadmap's verification is the comparison itself: a direct chain
of named letters against one group announcement, same world shape,
same measure.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.experiments.rumor import (
    GROUP,
    RUMOR,
    ChainPolicy,
    CrierPolicy,
    knows_fact,
    run_comparison,
    run_condition,
)
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.population import PopulationManager, SpawnRule
from app.simulation.world import SPEECH_BUFFER, Position, World


def _world() -> World:
    return World.generate("net-test", 24, 24)


def _two_populations() -> tuple[Engine, PopulationManager]:
    """Three agents, two populations: 1+2 share, 3 stands alone."""
    world = _world()
    engine = Engine(world, population_id=1)
    manager = PopulationManager(engine)
    engine.populations = manager
    manager.register(1, SpawnRule(name="a", members=2))
    manager.register(2, SpawnRule(name="b", members=1))
    manager.spawn_founding(1)
    manager.spawn_founding(2)
    return engine, manager


class TestTell:
    def test_a_letter_reaches_one_recipient_across_the_map(self):
        engine, _ = _two_populations()
        world = engine.world
        here = engine.agents[0]
        far = engine.agents[2]
        # Move the recipient out of earshot first: the letter must not
        # depend on proximity. Relocation rides the world's own
        # validated entry points.
        spot = next(
            Position(x, y)
            for y in range(world.height - 1, 0, -1)
            for x in range(world.width - 1, 0, -1)
            if abs(x - here.position.x) + abs(y - here.position.y) > 6
            and world.is_floor(Position(x, y))
            and world.object_at(Position(x, y)) is None
            and world.entity_at(Position(x, y)) is None
        )
        world.remove_entity(far.agent_id)
        world.add_entity(far.agent_id, spot)
        assert abs(far.position.x - here.position.x) + abs(far.position.y - here.position.y) > 6

        result = engine.world.execute_action(
            here.agent_id, {"action": "tell", "target": far.agent_id, "message": "come here"}
        )

        assert result.ok
        heard = engine.world.messages_for(far.agent_id)
        assert len(heard) == 1
        assert heard[0]["from"] == here.agent_id
        assert heard[0]["kind"] == "tell"
        assert heard[0]["to"] == far.agent_id

    def test_nobody_else_hears_the_letter(self):
        engine, _ = _two_populations()

        engine.world.execute_action(1, {"action": "tell", "target": 3, "message": "secret"})

        assert engine.world.messages_for(2) == []
        assert engine.world.messages_for(1) == []  # senders do not hear themselves

    def test_letters_are_recorded_as_direct_events(self):
        engine, _ = _two_populations()

        engine.world.execute_action(1, {"action": "tell", "target": 2, "message": "hi"})

        events = [e for e in engine.world.events if e.type == EventTypes.DIRECT]
        assert len(events) == 1
        assert events[0].actor_id == 1
        assert events[0].target_id == 2
        assert events[0].payload["message"] == "hi"

    def test_letters_to_self_the_void_and_silence_are_rejected(self):
        engine, _ = _two_populations()
        world = engine.world

        assert world.execute_action(1, {"action": "tell", "target": 1, "message": "me"}).reason == "cannot_target_self"
        assert world.execute_action(1, {"action": "tell", "target": 99, "message": "you"}).reason == "unknown_target"
        assert world.execute_action(1, {"action": "tell", "target": "two", "message": "you"}).reason == "invalid_target"
        assert world.execute_action(1, {"action": "tell", "target": 2, "message": "  "}).reason == "empty_message"
        assert all(e.type != EventTypes.DIRECT for e in world.events)


class TestAnnounce:
    def test_a_team_hears_its_crier(self):
        engine, _ = _two_populations()
        engine.world.add_to_team(1, 7)
        engine.world.add_to_team(2, 7)

        result = engine.world.execute_action(
            1, {"action": "announce", "scope": "team", "message": "huddle"}
        )

        assert result.ok
        assert result.data["recipients"] == [2]
        heard = engine.world.messages_for(2)
        assert len(heard) == 1
        assert heard[0]["kind"] == "announce"
        assert heard[0]["scope"] == "team"
        assert engine.world.messages_for(3) == []
        assert engine.world.messages_for(1) == []

    def test_a_population_hears_its_crier(self):
        engine, _ = _two_populations()

        result = engine.world.execute_action(
            1, {"action": "announce", "scope": "population", "message": "kin meet"}
        )

        assert result.ok
        assert result.data["recipients"] == [2]
        assert [m["kind"] for m in engine.world.messages_for(2)] == ["announce"]
        assert engine.world.messages_for(3) == []  # the other population is not told

    def test_announcements_are_recorded_with_scope_and_recipients(self):
        engine, _ = _two_populations()

        engine.world.execute_action(1, {"action": "announce", "scope": "population", "message": "kin"})

        events = [e for e in engine.world.events if e.type == EventTypes.ANNOUNCE]
        assert len(events) == 1
        assert events[0].payload["scope"] == "population"
        assert events[0].payload["recipients"] == [2]

    def test_announcing_to_no_group_is_a_rejection(self):
        engine, _ = _two_populations()
        world = engine.world

        assert world.execute_action(1, {"action": "announce", "scope": "team", "message": "x"}).reason == "not_on_a_team"
        assert world.execute_action(1, {"action": "announce", "scope": "clan", "message": "x"}).reason == "unknown_scope"
        # An entity with no population (the participant's shape) cannot
        # announce to one.
        world.add_entity(1001, Position(10, 10))
        assert world.execute_action(1001, {"action": "announce", "scope": "population", "message": "x"}).reason == "no_population"


class TestBroadcast:
    def test_everyone_hears_except_the_crier(self):
        engine, _ = _two_populations()

        result = engine.world.execute_action(3, {"action": "broadcast", "message": "hear ye"})

        assert result.ok
        assert result.data["recipients"] == [1, 2]
        assert [m["kind"] for m in engine.world.messages_for(1)] == ["broadcast"]
        assert [m["kind"] for m in engine.world.messages_for(2)] == ["broadcast"]
        assert all(m["from"] != 3 for m in engine.world.messages_for(3))

    def test_broadcasts_are_recorded(self):
        engine, _ = _two_populations()

        engine.world.execute_action(1, {"action": "broadcast", "message": "news"})

        events = [e for e in engine.world.events if e.type == EventTypes.BROADCAST]
        assert len(events) == 1
        assert events[0].payload["recipients"] == [2, 3]

    def test_silence_is_rejected(self):
        engine, _ = _two_populations()
        assert engine.world.execute_action(1, {"action": "broadcast", "message": ""}).reason == "empty_message"


class TestRouting:
    def test_local_speech_still_says_its_kind(self):
        engine, _ = _two_populations()
        world = engine.world
        # Agents 1 and 2 found beside each other, inside earshot.
        world.execute_action(1, {"action": "say", "message": "hello neighbor"})

        heard = [m for m in world.messages_for(2) if m["from"] == 1]
        assert heard and all(m["kind"] == "say" for m in heard)
        assert all("distance" in m for m in heard)

    def test_the_letter_buffer_is_bounded(self):
        engine, _ = _two_populations()
        world = engine.world

        for n in range(SPEECH_BUFFER + 5):
            world.execute_action(1, {"action": "tell", "target": 2, "message": f"note {n}"})

        assert len(world._letters) == SPEECH_BUFFER
        assert world.messages_for(2)[0]["message"] == "note 5"  # oldest rolled off

    def test_unroutable_messages_raise_before_recording(self):
        engine, _ = _two_populations()
        world = engine.world

        with pytest.raises(ValueError, match="unknown sender"):
            world.route_message(99, "broadcast", "all")
        with pytest.raises(ValueError, match="cannot route"):
            world.route_message(1, "whisper", "all")
        assert all(
            e.type not in (EventTypes.DIRECT, EventTypes.ANNOUNCE, EventTypes.BROADCAST)
            for e in world.events
        )

    def test_leaving_drops_group_membership(self):
        engine, _ = _two_populations()
        world = engine.world

        world.remove_entity(2)

        assert world.population_of(2) is None
        result = world.execute_action(1, {"action": "announce", "scope": "population", "message": "x"})
        assert result.data["recipients"] == []


class TestRumorPolicies:
    def test_a_link_relays_a_beat_after_learning(self):
        policy = ChainPolicy(successor=2)
        observation = {
            "self": {"tick": 4},
            "messages": [{"message": RUMOR, "tick": 4, "kind": "tell"}],
        }

        assert policy.decide(observation) == {"action": {"action": "look"}}
        observation["self"] = {"tick": 5}
        assert policy.decide(observation) == {
            "action": {"action": "tell", "target": 2, "message": RUMOR}
        }

    def test_the_last_link_only_listens(self):
        policy = ChainPolicy(successor=None, already_knows=True)
        observation = {"self": {"tick": 9}, "messages": []}

        assert policy.decide(observation) == {"action": {"action": "look"}}

    def test_the_crier_announces_once(self):
        policy = CrierPolicy(already_knows=True)
        observation = {"self": {"tick": 1}, "messages": []}

        first = policy.decide(observation)
        assert first["action"]["action"] == "announce"
        assert first["action"]["scope"] == "population"
        assert policy.decide(observation) == {"action": {"action": "look"}}

    def test_knowing_is_an_inbox_fact(self):
        assert knows_fact([{"message": RUMOR}]) is True
        assert knows_fact([{"message": "other gossip"}]) is False


class TestRumorExperiment:
    @pytest.fixture()
    def session_factory(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'rumor.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()

    def test_the_chain_informs_everyone_one_hop_per_tick(self, session_factory):
        record = run_condition(
            session_factory=session_factory, condition="direct", agents=5, seed="chain"
        )

        assert record["ticks_to_all"] == 4
        assert record["messages_sent"] == 4
        assert record["informed_history"] == [2, 3, 4, 5]

    def test_one_announcement_informs_everyone_at_once(self, session_factory):
        record = run_condition(
            session_factory=session_factory, condition=GROUP, agents=5, seed="crier"
        )

        assert record["ticks_to_all"] == 1
        assert record["messages_sent"] == 1
        assert record["informed_history"] == [5]

    def test_the_comparison_is_the_verdict(self, session_factory):
        report = run_comparison(session_factory=session_factory, agents=6, seed="versus")

        assert report["comparison"]["faster"] == GROUP
        assert report["comparison"]["ticks_saved"] == 4
        assert report["comparison"]["messages_saved"] == 4

    def test_the_runs_are_deterministic(self, session_factory):
        first = run_condition(
            session_factory=session_factory, condition="direct", agents=4, seed="same"
        )
        second = run_condition(
            session_factory=session_factory, condition="direct", agents=4, seed="same"
        )

        assert first["informed_history"] == second["informed_history"]
        assert first["ticks_to_all"] == second["ticks_to_all"] == 3

    def test_bad_conditions_and_lonely_rumors_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown condition"):
            run_condition(session_factory=session_factory, condition="shout", agents=3)
        with pytest.raises(ValueError, match="at least 2 agents"):
            run_condition(session_factory=session_factory, condition="direct", agents=1)

    def test_the_experiment_row_completes(self, session_factory):
        record = run_condition(
            session_factory=session_factory, condition=GROUP, agents=3, seed="row"
        )

        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "rumor"
            assert experiment.model_configuration["ticks_to_all"] == 1


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
        full = {"seed": "s28", "agents": 2, "autostart": False}
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def test_an_agent_tells_through_the_injection_route(self, client):
        world = self._create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "tell", "target": 2, "message": "over here"}},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        events = client.get(f"/api/worlds/{world['id']}/events?since_id=0&limit=50").json()
        assert any(e["type"] == "DIRECT" for e in events["events"])

    def test_the_participant_broadcasts_through_the_injection_route(self, client):
        world = self._create(client)
        joined = client.post(f"/api/worlds/{world['id']}/participant/join").json()
        participant = joined["entity_id"]

        response = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": participant, "action": {"action": "broadcast", "message": "hear ye"}},
        )

        assert response.json()["ok"] is True
        events = client.get(f"/api/worlds/{world['id']}/events?since_id=0&limit=50").json()
        assert any(e["type"] == "BROADCAST" for e in events["events"])

    def test_rejections_travel_the_route_not_exceptions(self, client):
        world = self._create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "tell", "target": 1, "message": "me"}},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is False
