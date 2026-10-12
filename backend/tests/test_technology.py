"""S29 â€” technology and cultural objects: recipes, patterns, tools,
inventions, and the cumulative-culture verification.

The roadmap's check â€” "an agent discovers an object/recipe and a
descendant can use it" â€” is the last test class; everything before it
is the machinery that check rests on.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.experiments.technology import (
    ANCHOR,
    HeirPolicy,
    InventorPolicy,
    pattern_script,
    run_cumulative_culture,
)
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.technology import (
    BASE_RECIPES,
    INVENTIONS,
    Pattern,
    Recipe,
    invention_for,
    is_technology,
    knowledge_item,
)
from app.simulation.world import Position, Terrain, World


def _world() -> tuple[World, Engine]:
    world = World.generate("tech-test", 24, 24)
    engine = Engine(world, population_id=1)
    engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(2, 2))
    return world, engine


def _with_tree(world: World, quantity: int = 4) -> None:
    world.place_object(
        "tree", Position(2, 3), properties={"quantity": quantity, "resource": "wood"}
    )


class TestRecipeData:
    def test_recipes_are_data(self):
        recipe = Recipe("flint_knife", {"stone": 1}, "knife", "an edge")

        assert recipe.name == "flint_knife"
        assert recipe.affordable_by({"stone": 1}) is True
        assert recipe.affordable_by({"stone": 0}) is False

    def test_malformed_recipes_are_rejected(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            Recipe("free", {"wood": 0}, "wood_block")
        with pytest.raises(ValueError, match="must produce something"):
            Recipe("nothing", {"wood": 1}, "")

    def test_patterns_are_data(self):
        pattern = Pattern("corner", ((0, 0, "wood_block"), (1, 0, "wood_block")))

        assert pattern.to_dict()["blocks"] == [[0, 0, "wood_block"], [1, 0, "wood_block"]]
        with pytest.raises(ValueError, match="at least one block"):
            Pattern("empty", ())
        with pytest.raises(ValueError, match="malformed"):
            Pattern("bad", ((0, 0),))

    def test_the_block_costs_come_from_the_recipe_data(self):
        from app.simulation.world import BLOCK_RECIPES

        assert BLOCK_RECIPES == {
            name: dict(recipe.inputs)
            for name, recipe in BASE_RECIPES.items()
            if name in ("wood_block", "stone_block", "door")
        }

    def test_knowledge_strings_name_technology(self):
        assert knowledge_item(BASE_RECIPES["wood_axe"]) == "recipe:wood_axe"
        assert is_technology("pattern:shelter_ring") is True
        assert is_technology("trees give wood") is False


class TestInventions:
    def test_combining_is_deterministic_and_symmetric(self):
        either = invention_for("recipe:wood_axe", "recipe:wood_block")
        reverse = invention_for("recipe:wood_block", "recipe:wood_axe")
        assert either is reverse
        assert isinstance(either, Pattern)
        assert either.name == "shelter_ring"

    def test_unknown_combinations_make_nothing(self):
        assert invention_for("recipe:wood_axe", "fact:the sky") is None

    def test_the_invented_pattern_is_a_closed_ring(self):
        pattern = INVENTIONS[("recipe:wood_axe", "recipe:wood_block")]

        cells = {(dx, dy) for dx, dy, _ in pattern.blocks}
        assert len(cells) == 12
        # Every ring cell; no interior cell is part of the pattern.
        assert (1, 1) not in cells and (2, 2) not in cells


class TestDiscovery:
    def test_experimenting_teaches_a_recipe(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 2)

        result = world.execute_action(1, {"action": "discover"})

        assert result.ok
        assert result.data["discovered"] == "door"  # first affordable, by name
        assert world.known_recipes(1) == ["door"]

    def test_discovery_needs_something_to_experiment_with(self):
        world, engine = _world()

        result = world.execute_action(1, {"action": "discover"})

        assert result.reason == "nothing_to_discover"
        assert world.known_recipes(1) == []

    def test_discovery_is_recorded_on_the_timeline(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 2)

        world.execute_action(1, {"action": "discover"})

        events = [e for e in world.events if e.type == EventTypes.INVENTION]
        assert len(events) == 1
        assert events[0].payload["kind"] == "discovery"
        assert events[0].payload["name"] == "door"


class TestCrafting:
    def test_crafting_makes_the_thing_carried(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 3)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})  # the axe recipe

        result = world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        assert result.ok
        assert result.data["object_type"] == "axe"
        assert world.resource_count(1, "wood") == 1  # 2 spent
        carried = world.carried_objects(1)
        assert len(carried) == 1
        assert carried[0]["type"] == "axe"
        assert carried[0]["properties"]["recipe"] == "wood_axe"

    def test_crafting_needs_the_recipe(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 3)

        result = world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        assert result.reason == "unknown_recipe"
        assert world.carried_objects(1) == []

    def test_crafting_spends_exactly(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        again = world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        assert again.reason == "insufficient_materials"
        assert world.resource_count(1, "wood") == 0
        assert len(world.carried_objects(1)) == 1

    def test_crafting_is_recorded(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        events = [e for e in world.events if e.type == EventTypes.CRAFT]
        assert len(events) == 1
        assert events[0].payload["object_type"] == "axe"


class TestTools:
    def test_the_axe_doubles_a_gather(self):
        world, _engine = _world()
        _with_tree(world, quantity=4)
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})

        result = world.execute_action(1, {"action": "gather", "resource": "wood"})

        assert result.ok
        assert result.data["amount"] == 2
        assert world.resource_count(1, "wood") == 2  # the grant, spent on the axe, then doubled back
        assert world.object_at(Position(2, 3)).properties["quantity"] == 2  # conservation

    def test_without_the_tool_a_gather_is_one(self):
        world, engine = _world()
        _with_tree(world, quantity=4)

        result = world.execute_action(1, {"action": "gather", "resource": "wood"})

        assert result.data["amount"] == 1

    def test_a_tool_dropped_no_longer_helps(self):
        world, engine = _world()
        _with_tree(world, quantity=4)
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "craft", "recipe": "wood_axe"})
        world.execute_action(1, {"action": "gather", "resource": "wood"})
        axe = world.inventory(1)[0]
        world.execute_action(1, {"action": "drop", "object_id": axe})

        assert world.tool_effect(1, "gather") == 1
        again = world.execute_action(1, {"action": "gather", "resource": "wood"})
        assert again.data["amount"] == 1


class TestInventing:
    def test_two_known_items_make_one_new_thing(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 4)
        for _ in range(3):  # door, wood_axe, wood_block
            world.execute_action(1, {"action": "discover"})

        result = world.execute_action(
            1,
            {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"},
        )

        assert result.ok
        assert result.data["invented"] == "pattern:shelter_ring"
        assert result.data["kind"] == "pattern"
        assert "shelter_ring" in world.patterns
        assert world.known_patterns(1) == ["shelter_ring"]

    def test_the_invention_is_recorded(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 4)
        for _ in range(3):
            world.execute_action(1, {"action": "discover"})
        world.execute_action(
            1, {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}
        )

        events = [
            e for e in world.events if e.type == EventTypes.INVENTION and e.payload.get("kind") == "invention"
        ]
        assert len(events) == 1
        assert events[0].payload["result"] == "pattern:shelter_ring"
        assert events[0].payload["result_kind"] == "pattern"

    def test_you_cannot_invent_what_you_do_not_know(self):
        world, engine = _world()

        result = world.execute_action(
            1, {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}
        )

        assert result.reason == "unknown_knowledge"

    def test_unknown_combinations_and_repeats_are_refused(self):
        world, engine = _world()
        world.credit_resource(1, "wood", 4)
        for _ in range(3):
            world.execute_action(1, {"action": "discover"})

        no_chemistry = world.execute_action(
            1, {"action": "invent", "a": "recipe:door", "b": "recipe:wood_axe"}
        )
        assert no_chemistry.reason == "no_such_invention"

        world.execute_action(
            1, {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}
        )
        again = world.execute_action(
            1, {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}
        )
        assert again.reason == "already_invented"


class TestObservation:
    def test_a_mind_sees_its_culture_and_its_hands(self):
        world, engine = _world()
        agent = engine.agents[0]
        world.credit_resource(agent.agent_id, "wood", 2)
        world.execute_action(agent.agent_id, {"action": "discover"})
        world.execute_action(agent.agent_id, {"action": "discover"})
        world.execute_action(agent.agent_id, {"action": "craft", "recipe": "wood_axe"})

        observation = agent.observe()

        assert observation["technology"]["recipes"] == ["door", "wood_axe"]
        assert observation["technology"]["patterns"] == []
        assert [item["type"] for item in observation["carried"]] == ["axe"]


class TestCumulativeInheritance:
    def test_a_child_inherits_its_parents_discoveries(self):
        world = World.generate("cumulative", 24, 24)
        engine = Engine(world, population_id=1)
        parent = Agent(agent_id=1, policy=WanderPolicy())
        engine.spawn_agent(parent, Position(2, 2))
        world.credit_resource(1, "wood", 2)
        world.execute_action(1, {"action": "discover"})
        world.execute_action(1, {"action": "discover"})

        child = engine.create_child(1)

        # The parent declared nothing: the discoveries still travel.
        assert "recipe:door" in child.knowledge
        assert "recipe:wood_axe" in child.knowledge
        assert world.known_recipes(child.agent_id) == ["door", "wood_axe"]

    def test_an_inherited_recipe_is_usable_without_rediscovery(self):
        world = World.generate("usable", 24, 24)
        engine = Engine(world, population_id=1)
        parent = Agent(agent_id=1, policy=WanderPolicy())
        engine.spawn_agent(parent, Position(2, 2))
        world.credit_resource(1, "wood", 4)
        for _ in range(3):
            world.execute_action(1, {"action": "discover"})
        world.execute_action(
            1, {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}
        )

        child = engine.create_child(1)
        world.credit_resource(child.agent_id, "wood", 2)

        crafted = world.execute_action(
            child.agent_id, {"action": "craft", "recipe": "wood_axe"}
        )

        assert crafted.ok
        assert world.known_patterns(child.agent_id) == ["shelter_ring"]

    def test_nonsense_knowledge_never_breaks_a_birth(self):
        world = World.generate("typo", 24, 24)
        engine = Engine(world, population_id=1)
        parent = Agent(agent_id=1, policy=WanderPolicy())
        engine.spawn_agent(parent, Position(2, 2))

        child = engine.create_child(
            1, inheritance={"knowledge": ["recipe:nonexistent", "trees give wood"]}
        )

        assert child.knowledge == ["recipe:nonexistent", "trees give wood"]
        assert world.known_recipes(child.agent_id) == []


class TestPatternScript:
    def test_the_script_lays_every_block_and_never_self_blocks(self):
        pattern = INVENTIONS[("recipe:wood_axe", "recipe:wood_block")]
        script = pattern_script((2, 2), ANCHOR, pattern)

        builds = [direction for verb, direction in script if verb == "build"]
        assert len(builds) == len(pattern.blocks)

        # Walk the script on an empty lot: every move and build lands.
        world = World(
            "script",
            24,
            24,
            terrain=[[Terrain.FLOOR] * 24 for _ in range(24)],
        )
        engine = Engine(world, population_id=1)
        policy = HeirPolicy(pattern, ANCHOR, (2, 2))
        agent = Agent(agent_id=1, policy=policy, observation_radius=3)
        engine.spawn_agent(agent, Position(2, 2))
        world.credit_resource(1, "wood", 12)
        for _ in range(len(script) + 4):
            engine.step()

        assert policy.blocks_built == 12
        assert len(world.structures()) == 1
        assert world.structures()[0].purpose == "shelter"


class TestCumulativeCultureExperiment:
    @pytest.fixture()
    def session_factory(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'culture.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()

    def test_the_roadmap_verification(self, session_factory):
        """A parent discovers; the descendant uses â€” culture is cumulative."""
        record = run_cumulative_culture(session_factory=session_factory, seed="verify")

        parent = record["parent"]
        assert parent["discoveries"] == 3
        assert parent["crafts"] == 1
        assert parent["inventions"] == 1
        assert parent["tool_yield"] == 2  # the axe pays for itself

        child = record["child"]
        assert child["generation"] == 1
        assert child["discoveries"] == 0  # no rediscovery
        assert child["crafts"] == 1  # crafted the inherited recipe
        assert child["blocks_built"] == 12  # built the inherited pattern
        assert child["structures_built"] == 1
        assert child["tool_yield"] == 2  # and used the inherited tool
        assert set(child["known_recipes"]) == {"door", "wood_axe", "wood_block"}
        assert child["known_patterns"] == ["shelter_ring"]

        cumulative = record["cumulative"]
        assert cumulative["child_crafted_without_discovering"] is True
        assert cumulative["descendant_built_the_pattern"] is True
        assert cumulative["descendant_used_the_tool"] is True

    def test_the_run_is_deterministic(self, session_factory):
        first = run_cumulative_culture(session_factory=session_factory, seed="same")
        second = run_cumulative_culture(session_factory=session_factory, seed="same")

        assert first["cumulative"] == second["cumulative"]
        assert first["child"]["blocks_built"] == second["child"]["blocks_built"]

    def test_unknown_modes_rejected(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_cumulative_culture(session_factory=session_factory, mode="shout")

    def test_the_experiment_row_completes(self, session_factory):
        record = run_cumulative_culture(session_factory=session_factory, seed="row")

        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "culture"
            assert experiment.model_configuration["descendant_built_the_pattern"] is True


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
        full = {"seed": "s29", "agents": 2, "autostart": False}
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def _funded(self, client: TestClient, **payload) -> dict:
        """A world whose lone builder is granted wood to work with."""
        full = {
            "seed": "s29-funded",
            "autostart": False,
            "populations": [
                {"name": "builders", "members": 1, "stipend": {"wood": 4}}
            ],
        }
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def test_technology_lives_in_the_agents_detail(self, client):
        world = self._create(client)

        detail = client.get(f"/api/worlds/{world['id']}/agents/1").json()

        assert detail["technology"] == {"recipes": [], "patterns": [], "carried": []}

    def test_discoveries_and_crafts_ride_the_injection_route(self, client):
        world = self._funded(client)

        discovered = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "discover"}},
        )
        assert discovered.json()["ok"] is True
        crafted = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "craft", "recipe": "door"}},
        )

        assert crafted.json()["ok"] is True
        detail = client.get(f"/api/worlds/{world['id']}/agents/1").json()
        assert detail["technology"]["recipes"] == ["door"]
        assert [item["type"] for item in detail["technology"]["carried"]] == ["door"]

    def test_discovery_without_materials_is_a_rejection_not_an_error(self, client):
        world = self._create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": 1, "action": {"action": "discover"}},
        )

        assert response.status_code == 200
        assert response.json()["reason"] == "nothing_to_discover"

    def test_an_invention_lands_in_the_worlds_technology(self, client):
        world = self._funded(client)
        for _ in range(3):  # door, wood_axe, wood_block
            client.post(
                f"/api/worlds/{world['id']}/actions",
                json={"agent_id": 1, "action": {"action": "discover"}},
            )
        client.post(
            f"/api/worlds/{world['id']}/actions",
            json={
                "agent_id": 1,
                "action": {
                    "action": "invent",
                    "a": "recipe:wood_axe",
                    "b": "recipe:wood_block",
                },
            },
        )

        body = client.get(f"/api/worlds/{world['id']}/technology").json()

        assert "wood_axe" in [recipe["name"] for recipe in body["recipes"]]
        assert [pattern["name"] for pattern in body["patterns"]] == ["shelter_ring"]
        inventions = body["inventions"]
        assert len(inventions) == 4  # three discoveries and the invention
        assert inventions[-1]["kind"] == "invention"
        assert inventions[-1]["result"] == "pattern:shelter_ring"

    def test_the_worlds_technology_route(self, client):
        world = self._create(client)

        body = client.get(f"/api/worlds/{world['id']}/technology").json()

        assert "wood_axe" in [recipe["name"] for recipe in body["recipes"]]
        assert body["patterns"] == []  # nothing invented yet
        assert body["inventions"] == []
