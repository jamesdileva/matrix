"""S27 — the population manager: groups, spawn rules, statistics,
relationships.

The roadmap's verification is "run multiple populations
simultaneously", so most of this is exactly that: two rules, one
world, and the facts that must hold about the groups afterwards.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.errors import BirthError
from app.simulation.events import EventTypes
from app.simulation.policies import GathererPolicy, WanderPolicy
from app.simulation.population import PopulationManager, SpawnRule
from app.simulation.world import Position, World


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pop.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _managed_world(rule: SpawnRule, *, width: int = 24, height: int = 24, second: SpawnRule | None = None):
    """A world with one (or two) governed populations, already founded."""
    world = World.generate("pop-test", width, height)
    engine = Engine(world, population_id=1)
    manager = PopulationManager(engine)
    engine.populations = manager
    manager.register(1, rule)
    manager.spawn_founding(1)
    if second is not None:
        manager.register(2, second)
        manager.spawn_founding(2)
    return engine, manager


class TestPopulations:
    def test_two_groups_inhabit_one_world(self):
        engine, manager = _managed_world(
            SpawnRule(name="builders", members=2),
            second=SpawnRule(name="wanderers", members=3, policies=("forage",)),
        )

        assert len(manager.members(1)) == 2
        assert len(manager.members(2)) == 3
        assert len(engine.agents) == 5
        # Membership is shared world-wide: everyone sees everyone.
        assert len(manager.relationships(1)) == 4

    def test_a_group_keeps_its_own_minds(self):
        engine, manager = _managed_world(
            SpawnRule(name="guild", members=3, policies=("wander", "gather", "wander"))
        )

        kinds = [type(a.policy).__name__ for a in engine.agents]
        assert kinds == ["WanderPolicy", "GathererPolicy", "WanderPolicy"]
        # The gatherer keeps its wider observation radius.
        assert engine.agents[1].observation_radius == 4

    def test_a_population_may_start_empty(self):
        engine, manager = _managed_world(SpawnRule(name="seed", members=0, top_up=True))

        assert engine.agents == []
        assert manager.spawn_arrival(1) is not None
        assert len(manager.members(1)) == 1

    def test_duplicate_registration_is_an_error(self):
        _engine, manager = _managed_world(SpawnRule(name="one", members=1))
        with pytest.raises(ValueError, match="already registered"):
            manager.register(1, SpawnRule(name="again", members=1))


class TestSpawnRules:
    def test_the_zone_holds_the_founding_group(self):
        engine, manager = _managed_world(
            SpawnRule(name="zoned", members=3, spawn_zone=(2, 2, 4, 4))
        )

        for agent in engine.agents:
            assert 2 <= agent.position.x <= 4 and 2 <= agent.position.y <= 4

    def test_a_zone_that_cannot_fit_is_an_error_not_an_overflow(self):
        world = World.generate("tight", 16, 16)
        engine = Engine(world, population_id=1)
        manager = PopulationManager(engine)
        engine.populations = manager
        # One cell of zone, two founding members: the second has nowhere
        # to stand, and that must be loud rather than silently outside
        # the group's own territory.
        manager.register(1, SpawnRule(name="tight", members=2, spawn_zone=(2, 2, 2, 2)))
        with pytest.raises(ValueError, match="no free cell in its spawn zone"):
            manager.spawn_founding(1)

    def test_a_zone_outside_the_world_is_rejected(self):
        world = World.generate("far", 24, 24)
        engine = Engine(world, population_id=1)
        manager = PopulationManager(engine)
        engine.populations = manager
        manager.register(1, SpawnRule(name="far", members=1, spawn_zone=(100, 100, 104, 104)))
        with pytest.raises(ValueError, match="outside the"):
            manager.spawn_founding(1)

    def test_top_up_replaces_losses_on_its_own(self):
        engine, manager = _managed_world(
            SpawnRule(name="renewing", members=3, top_up=True)
        )
        # Members "die" the only way they currently can: they leave.
        gone = engine.agents[0]
        world = engine.world
        world.remove_entity(gone.agent_id)
        engine._agents.pop(gone.agent_id)

        spawned = manager.enforce_spawn_rules()

        assert len(spawned) == 1
        assert len(manager.members(1)) == 3

    def test_top_up_stops_at_the_cap(self):
        _engine, manager = _managed_world(
            SpawnRule(name="capped", members=2, max_members=3, top_up=True)
        )

        assert manager.can_reproduce(1) is True
        manager.spawn_arrival(1)
        assert manager.can_reproduce(1) is False
        assert manager.spawn_arrival(1) is None

    def test_the_cap_is_the_rules_not_the_parents(self):
        engine, manager = _managed_world(
            SpawnRule(name="capped", members=1, max_members=1)
        )

        with pytest.raises(BirthError, match="member limit"):
            engine.create_child(engine.agents[0].agent_id)

    def test_an_ungoverned_population_has_no_cap(self):
        engine = Engine(World.generate("free", 16, 16), population_id=7)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
        # No manager at all: reproduction is ungoverned.
        child = engine.create_child(1)
        assert child.population_id == 7

    def test_the_stipend_arrives_with_the_member(self):
        engine, manager = _managed_world(
            SpawnRule(name="funded", members=2, stipend={"wood": 4, "stone": 0})
        )

        for agent in engine.agents:
            assert engine.world.resources(agent.agent_id)["wood"] == 4

    def test_founding_is_recorded_on_the_timeline(self):
        _engine, manager = _managed_world(SpawnRule(name="founded", members=2))

        events = [e for e in _engine.world.events if e.type == EventTypes.POPULATION_SPAWN]
        assert len(events) == 1
        assert events[0].payload["kind"] == "founding"
        assert events[0].payload["members"] == [1, 2]
        assert events[0].payload["name"] == "founded"


class TestRuleValidation:
    def test_a_population_needs_a_name(self):
        with pytest.raises(ValueError, match="non-empty name"):
            SpawnRule(name="")

    def test_a_cap_below_the_founding_size_is_rejected(self):
        with pytest.raises(ValueError, match="must be >= members"):
            SpawnRule(name="small", members=4, max_members=2)

    def test_an_inverted_zone_is_rejected(self):
        with pytest.raises(ValueError, match="x0<=x1"):
            SpawnRule(name="upside", members=1, spawn_zone=(5, 5, 2, 2))

    def test_a_negative_stipend_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            SpawnRule(name="cheat", members=1, stipend={"wood": -1})

    def test_rules_survive_json(self):
        rule = SpawnRule(
            name="round",
            members=2,
            policies=("wander", "gather"),
            spawn_zone=(1, 1, 6, 6),
            max_members=5,
            top_up=True,
            stipend={"wood": 2},
        )
        assert SpawnRule.from_dict(rule.to_dict()) == rule


class TestStatistics:
    def test_statistics_describe_the_group(self):
        engine, manager = _managed_world(
            SpawnRule(
                name="measured",
                members=3,
                max_members=6,
                stipend={"wood": 2},
                top_up=True,
            )
        )
        engine.world.credit_resource(1, "wood", 3)

        stats = manager.statistics(1)

        assert stats["name"] == "measured"
        assert stats["size"] == 3
        assert stats["max_members"] == 6
        assert stats["top_up"] is True
        assert stats["generation"] == {"min": 0, "max": 0, "average": 0}
        assert stats["brains"] == {"model": 0, "scripted": 3}
        assert stats["resources"] == {"wood": 9}  # 2 each, plus one gift
        assert stats["arrivals"] == 0
        assert stats["age_ticks"] == engine.world.tick

    def test_world_statistics_add_the_groups_up(self):
        _engine, manager = _managed_world(
            SpawnRule(name="a", members=2, stipend={"wood": 1}),
            second=SpawnRule(name="b", members=2, stipend={"wood": 3}),
        )

        stats = manager.world_statistics()

        assert stats["totals"]["populations"] == 2
        assert stats["totals"]["agents"] == 4
        assert stats["totals"]["resources"]["wood"] == 8
        assert [p["name"] for p in stats["populations"]] == ["a", "b"]

    def test_a_birth_shows_up_as_a_statistic(self):
        engine, manager = _managed_world(SpawnRule(name="growing", members=1))

        engine.create_child(engine.agents[0].agent_id)

        stats = manager.statistics(1)
        assert stats["births"] == 1
        assert stats["size"] == 2
        assert stats["generation"]["max"] == 1

    def test_unknown_population_statistics_404(self):
        _engine, manager = _managed_world(SpawnRule(name="known", members=1))
        with pytest.raises(ValueError, match="unknown population"):
            manager.statistics(99)


class TestRelationships:
    def test_kin_from_the_lineage(self):
        engine, manager = _managed_world(SpawnRule(name="family", members=1))
        parent = engine.agents[0]
        child = engine.create_child(parent.agent_id)
        sibling = engine.create_child(parent.agent_id)

        assert manager.relationship(child.agent_id, parent.agent_id) == "parent"
        assert manager.relationship(parent.agent_id, child.agent_id) == "child"
        assert manager.relationship(child.agent_id, sibling.agent_id) == "sibling"
        kin = manager.kin(child.agent_id)
        assert kin["parent"] == parent.agent_id
        assert kin["siblings"] == [sibling.agent_id]
        assert kin["children"] == []

    def test_group_membership_is_the_boundary(self):
        _engine, manager = _managed_world(
            SpawnRule(name="inside", members=1),
            second=SpawnRule(name="outside", members=2),
        )

        assert manager.relationship(1, 2) == "stranger"  # across the boundary
        assert manager.relationship(2, 3) == "neighbor"  # inside one group

    def test_teammates_are_a_kind_of_kin_by_covenant(self):
        engine, manager = _managed_world(
            SpawnRule(name="pair", members=2),
            second=SpawnRule(name="loner", members=1),
        )
        engine.world.add_to_team(1, 9)
        engine.world.add_to_team(2, 9)

        assert manager.relationship(1, 2) == "teammate"
        assert manager.relationship(1, 3) == "stranger"

    def test_following_ranks_above_teammates(self):
        engine, manager = _managed_world(
            SpawnRule(name="retinue", members=2),
            second=SpawnRule(name="leaderish", members=1),
        )
        engine.world.add_to_team(1, 9)
        engine.world.add_to_team(3, 9)
        engine.world.set_follow(1, 3)
        engine.world.add_to_team(3, 9)

        assert manager.relationship(1, 3) == "leader"
        assert manager.relationship(3, 1) == "follower"

    def test_relationships_report_positions_and_distance(self):
        engine, manager = _managed_world(
            SpawnRule(name="grid", members=1),
            second=SpawnRule(name="near", members=1, spawn_zone=(8, 8, 8, 8)),
        )

        relations = manager.relationships(1)

        assert len(relations) == 1
        relation = relations[0]
        assert relation["agent_id"] == 2
        assert relation["kind"] == "stranger"
        assert relation["population_id"] == 2
        assert relation["distance"] >= 7

    def test_unknown_agents_have_no_relationships(self):
        _engine, manager = _managed_world(SpawnRule(name="one", members=1))
        with pytest.raises(ValueError, match="unknown agent"):
            manager.relationships(42)


class TestObservations:
    def test_an_agent_sees_its_group(self):
        engine, manager = _managed_world(SpawnRule(name="seen", members=3))

        observation = engine.agents[0].observe()

        assert observation["population"] == {"id": 1, "size": 3}

    def test_an_agent_without_a_provider_still_has_a_group(self):
        world = World.generate("plain", 16, 16)
        engine = Engine(world, population_id=4)
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))

        observation = engine.agents[0].observe()

        assert observation["population"] == {"id": 4, "size": None}


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
        response = client.post("/api/worlds", json={"seed": "s27", **payload})
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_world_with_several_populations(self, client):
        world = self._create(
            client,
            populations=[
                {"name": "builders", "members": 2, "policies": ["wander"]},
                {"name": "gatherers", "members": 2, "policies": ["gather"], "stipend": {"wood": 2}},
            ],
            autostart=False,
        )

        body = client.get(f"/api/worlds/{world['id']}/populations").json()

        assert body["totals"]["populations"] == 2
        assert body["totals"]["agents"] == 4
        assert [p["name"] for p in body["populations"]] == ["builders", "gatherers"]
        assert body["populations"][1]["resources"]["wood"] == 4
        # Two groups, one world, on the same timeline.
        groups = {
            agent["population_id"]
            for agent in client.get(f"/api/worlds/{world['id']}/agents").json()["agents"]
        }
        assert len(groups) == 2

    def test_a_population_founded_in_a_live_world(self, client):
        world = self._create(client, agents=2, autostart=False)

        created = client.post(
            f"/api/worlds/{world['id']}/populations",
            json={"name": "arrivals", "members": 2, "policies": ["forage"], "spawn_zone": [1, 1, 6, 6]},
        )

        assert created.status_code == 201
        population = created.json()["population"]
        assert population["name"] == "arrivals"
        assert population["size"] == 2
        listing = client.get(f"/api/worlds/{world['id']}/populations").json()
        assert listing["totals"]["populations"] == 2
        assert listing["totals"]["agents"] == 4

    def test_a_rule_the_world_cannot_honor_is_a_400(self, client):
        world = self._create(client, agents=1, autostart=False)

        rejected = client.post(
            f"/api/worlds/{world['id']}/populations",
            json={"name": "impossible", "members": 2, "spawn_zone": [200, 200, 204, 204]},
        )

        assert rejected.status_code == 400

    def test_one_populations_statistics(self, client):
        world = self._create(client, agents=2, autostart=False)

        body = client.get(f"/api/worlds/{world['id']}/populations/1").json()

        population = body["population"]
        assert population["size"] == 2
        assert population["name"] == "population-1"

    def test_unknown_population_is_a_404(self, client):
        world = self._create(client, agents=1, autostart=False)

        assert client.get(f"/api/worlds/{world['id']}/populations/999").status_code == 404

    def test_relationships_route(self, client):
        world = self._create(
            client,
            populations=[
                {"name": "a", "members": 1},
                {"name": "b", "members": 1},
            ],
            autostart=False,
        )

        body = client.get(f"/api/worlds/{world['id']}/agents/1/relationships").json()

        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["kind"] == "stranger"

    def test_unknown_agent_relationships_is_a_404(self, client):
        world = self._create(client, agents=1, autostart=False)

        response = client.get(f"/api/worlds/{world['id']}/agents/999/relationships")

        assert response.status_code == 404

    def test_a_capped_population_refuses_births(self, client):
        world = self._create(
            client,
            populations=[{"name": "small", "members": 1, "max_members": 1}],
            autostart=False,
        )

        response = client.post(
            f"/api/worlds/{world['id']}/births", json={"parent_id": 1}
        )

        assert response.status_code == 409
