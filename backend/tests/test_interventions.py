"""S45 — intervention records, measurements, and knowledge removal."""

import pytest

from app.simulation.events import EventTypes
from app.simulation.geometry import Position
from app.simulation.interventions import (
    INTERVENTION_KINDS,
    Intervention,
    intervention_catalog,
    metric_delta,
    world_metrics,
)
from app.simulation.world import World


class FakeAgent:
    """The metric helper only needs the fields an Agent exposes."""

    def __init__(self, agent_id: int, position: Position, knowledge=None):
        self.agent_id = agent_id
        self.status = "alive"
        self.position = position
        self.knowledge = list(knowledge or [])


def test_catalog_names_all_six_interventions():
    catalog = intervention_catalog()
    assert [item["kind"] for item in catalog["kinds"]] == list(INTERVENTION_KINDS)
    for item in catalog["kinds"]:
        assert item["name"] and item["description"]
    assert "knowledge_facts" in catalog["metrics"]


def test_world_metrics_describe_physical_and_mental_state():
    world = World("metrics", 8, 8)
    world.add_entity(1, Position(1, 1))
    world.place_object("tree", Position(2, 2), properties={"quantity": 3})
    world.credit_resource(1, "wood", 2)
    agent = FakeAgent(1, Position(1, 1), ["fire is hot", "water is wet"])

    metrics = world_metrics(world, [agent])

    assert metrics["tick"] == 0
    assert metrics["entities"] == 1
    assert metrics["population"] == 1
    assert metrics["objects"] == 1
    assert metrics["knowledge_facts"] == 2
    assert metrics["resources"] == 2


def test_metric_delta_is_per_key_and_numeric():
    before = {"tick": 2, "objects": 1, "knowledge_facts": 0}
    current = {"tick": 5, "objects": 3, "knowledge_facts": 2}
    assert metric_delta(before, current) == {
        "tick": 3,
        "entities": 0,
        "population": 0,
        "objects": 2,
        "knowledge_facts": 2,
        "known_recipes": 0,
        "known_patterns": 0,
        "settlements": 0,
        "games": 0,
        "challenges_completed": 0,
        "messages": 0,
        "resources": 0,
    }


def test_recorded_intervention_has_baseline_event_and_round_trip():
    world = World("record", 8, 8)
    world.tick = 7
    world.add_entity(1, Position(1, 1))

    intervention = world.record_intervention(
        "provide_information",
        target=1,
        details={"facts": ["fire is hot"]},
        baseline={"tick": 7, "knowledge_facts": 0},
    )

    assert intervention.id == 1
    assert world.interventions == [intervention]
    assert world.intervention(1) is intervention
    event = world.events[-1]
    assert event.type == EventTypes.INTERVENTION
    assert event.payload["kind"] == "provide_information"
    assert event.payload["target"] == 1

    restored = World.from_dict(world.to_dict())
    assert restored.interventions == [intervention]
    assert restored.to_dict()["next_intervention_id"] == 2


def test_unknown_intervention_kinds_are_refused():
    world = World("refuse", 8, 8)
    with pytest.raises(ValueError, match="unknown intervention"):
        world.record_intervention("smite", target=1)
    with pytest.raises(ValueError, match="unknown intervention"):
        Intervention(id=1, kind="smite", tick=0, target=None)


def test_revoke_knowledge_takes_usable_technology_away():
    world = World("revoke", 8, 8)
    world.add_entity(1, Position(1, 1))
    granted = world.grant_knowledge(1, ["recipe:door", "recipe:wood_block"])
    assert granted == ["recipe:door", "recipe:wood_block"]
    assert world.known_recipes(1) == ["door", "wood_block"]

    revoked = world.revoke_knowledge(1, ["recipe:door"])

    assert revoked == ["recipe:door"]
    assert world.known_recipes(1) == ["wood_block"]
    assert world.revoke_knowledge(1, ["recipe:door"]) == []
