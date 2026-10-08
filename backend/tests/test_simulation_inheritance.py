"""S10 — inheritance: the package travels, and only the package travels.

The roadmap's four verification items each get a test here:

- the child receives the parent's *intended* inheritance;
- uninherited memory does not magically appear;
- inheritance is recorded (event + database);
- parent and child states remain independent after creation.
"""

import copy

import pytest

from app.models.decision import parse_decision
from app.simulation.agent import Agent, Policy
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.inheritance import InheritancePackage
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

PACKAGE = {
    "traits": {"curiosity": 0.9},
    "knowledge": ["water is wet", "the void is dark"],
    "message": "seek the green",
    "cultural_artifacts": [{"name": "first-stone", "type": "marker"}],
}


def _flat_engine(size: int = 24) -> Engine:
    terrain = [[Terrain.FLOOR] * size for _ in range(size)]
    return Engine(World("flat", size, size, terrain=terrain))


def _spawn(engine: Engine, agent_id: int = 1, **kwargs) -> Agent:
    agent = Agent(agent_id=agent_id, policy=WanderPolicy(), **kwargs)
    engine.spawn_agent(agent, Position(2, 2))
    return agent


class DeclaringPolicy(Policy):
    """A scripted mind that declares an inheritance intent in its decision."""

    def __init__(self, inheritance: dict) -> None:
        self._inheritance = inheritance

    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "look"}, "inheritance": self._inheritance}


class TestInheritancePackage:
    def test_from_dict_normalizes_parts(self):
        package = InheritancePackage.from_dict(PACKAGE)
        assert package.traits == {"curiosity": 0.9}
        assert package.knowledge == ("water is wet", "the void is dark")
        assert package.message == "seek the green"
        assert package.cultural_artifacts == ({"name": "first-stone", "type": "marker"},)

    def test_from_dict_tolerates_wrong_types(self):
        package = InheritancePackage.from_dict(
            {"traits": "nope", "knowledge": "nope", "message": 5, "cultural_artifacts": 7}
        )
        assert package.traits == {}
        assert package.knowledge == ()
        assert package.message is None
        assert package.cultural_artifacts == ()

    def test_as_dict_round_trips(self):
        package = InheritancePackage.from_dict(PACKAGE)
        assert InheritancePackage.from_dict(package.as_dict()).as_dict() == package.as_dict()

    def test_as_dict_is_json_safe(self):
        import json

        json.dumps(InheritancePackage.from_dict(PACKAGE).as_dict())


class TestChildReceivesIntent:
    def test_explicit_package_lands_on_the_child(self):
        engine = _flat_engine()
        _spawn(engine)

        child = engine.create_child(1, inheritance=PACKAGE)

        assert child.traits == PACKAGE["traits"]
        assert child.knowledge == PACKAGE["knowledge"]
        assert child.cultural_artifacts == PACKAGE["cultural_artifacts"]
        assert child.inheritance_received["message"] == "seek the green"
        # The message is also the child's first recollection (S09).
        assert child.memory.recent()[0]["reason"] == "seek the green"

    def test_parent_intent_is_used_by_default(self):
        # The parent declares intent through a decision; act() stores
        # it; create_child then transmits it without being told twice.
        engine = _flat_engine()
        parent = _spawn(engine)
        parent.policy = DeclaringPolicy(PACKAGE)

        parent.act()  # decision -> pending inheritance
        child = engine.create_child(1)

        assert child.knowledge == PACKAGE["knowledge"]
        assert child.traits == PACKAGE["traits"]

    def test_child_sees_inheritance_in_its_observation(self):
        engine = _flat_engine()
        _spawn(engine)
        child = engine.create_child(1, inheritance=PACKAGE)

        observation = child.observe()

        assert observation["traits"] == PACKAGE["traits"]
        assert observation["knowledge"] == PACKAGE["knowledge"]
        assert observation["cultural_artifacts"] == PACKAGE["cultural_artifacts"]


class TestUninheritedStaysBehind:
    def test_parent_state_without_intent_does_not_reach_the_child(self):
        engine = _flat_engine()
        parent = _spawn(engine, knowledge=["parent fact"], traits={"age": 3})
        parent.pending_inheritance = None  # no intent declared

        child = engine.create_child(1)

        assert child.knowledge == []
        assert child.traits == {}
        assert child.cultural_artifacts == []
        assert parent.knowledge == ["parent fact"]  # and the parent keeps it

    def test_empty_intent_transmits_nothing(self):
        engine = _flat_engine()
        parent = _spawn(engine, knowledge=["parent fact"])
        parent.pending_inheritance = {"message": "bye"}  # only a message

        child = engine.create_child(1)

        assert child.knowledge == []
        assert child.memory.recent()[0]["reason"] == "bye"


class TestIndependence:
    def test_child_mutation_does_not_touch_parent_intent(self):
        engine = _flat_engine()
        parent = _spawn(engine)
        parent.pending_inheritance = copy.deepcopy(PACKAGE)

        child = engine.create_child(1)
        child.knowledge.append("invented later")
        child.traits["curiosity"] = 0.1
        child.cultural_artifacts.append({"name": "new-thing"})

        assert parent.pending_inheritance["knowledge"] == PACKAGE["knowledge"]
        assert parent.pending_inheritance["traits"] == {"curiosity": 0.9}
        assert parent.pending_inheritance["cultural_artifacts"] == PACKAGE["cultural_artifacts"]

    def test_recorded_package_does_not_alias_later_mutation(self):
        engine = _flat_engine()
        _spawn(engine)
        child = engine.create_child(1, inheritance=PACKAGE)
        born = [e for e in engine.world.events if e.type == EventTypes.AGENT_BORN][-1]

        child.knowledge.append("added after birth")
        child.cultural_artifacts.clear()

        assert born.payload["inheritance"]["knowledge"] == PACKAGE["knowledge"]
        assert born.payload["inheritance"]["cultural_artifacts"] == PACKAGE["cultural_artifacts"]


class TestDecisionContract:
    def test_inheritance_field_parsed(self):
        decision = parse_decision('{"action": {"action": "look"}, "inheritance": %s}' % __import__("json").dumps(PACKAGE))
        assert decision.inheritance == PACKAGE
        assert decision.as_dict()["inheritance"] == PACKAGE

    def test_inheritance_wrong_type_dropped(self):
        decision = parse_decision('{"action": {"action": "look"}, "inheritance": "everything"}')
        assert decision.inheritance is None

    def test_founder_observation_has_empty_parts(self):
        engine = _flat_engine()
        founder = _spawn(engine)
        observation = founder.observe()
        assert observation["traits"] == {}
        assert observation["knowledge"] == []
        assert observation["cultural_artifacts"] == []
