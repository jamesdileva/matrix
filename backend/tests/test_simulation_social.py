"""S22 — social interaction in the engine: transfers and following.

The contract that matters: transfers are adjacent, validated before
anything moves, and every one lands on the timeline; an atomic trade
never half-applies; and a follow directive moves an entity with its
target until released.
"""

import pytest

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World

def _flat(size: int = 9) -> World:
    return World("t", size, size, terrain=[[Terrain.FLOOR] * size for _ in range(size)])


def _pair():
    """Two adjacent agents on a flat world, agent 1 holding an object."""
    world = _flat()
    engine = Engine(world)
    first = Agent(agent_id=1, policy=WanderPolicy())
    second = Agent(agent_id=2, policy=WanderPolicy())
    engine.spawn_agent(first, Position(4, 4))
    engine.spawn_agent(second, Position(5, 4))
    obj = world.place_object("food", Position(3, 4), properties={"quantity": 1})
    picked = world.execute_action(1, {"action": "pick_up", "object_id": obj.id})
    assert picked.ok, "fixture: the founder should hold the object"
    return engine, first, second, obj


class TestGiveAndTake:
    def test_give_moves_the_object_and_records_it(self):
        engine, first, second, obj = _pair()

        result = engine.world.execute_action(
            1, {"action": "give", "target": 2, "object_id": obj.id}
        )

        assert result.ok
        assert engine.world.inventory(1) == ()
        assert engine.world.inventory(2) == (obj.id,)
        transfers = [e for e in engine.world.events if e.type == EventTypes.TRANSFER]
        assert len(transfers) == 1
        assert transfers[0].payload == {
            "kind": "give",
            "what": "object",
            "object_id": obj.id,
            "type": "food",
        }

    def test_take_moves_it_the_other_way(self):
        engine, first, second, obj = _pair()
        engine.world.execute_action(1, {"action": "give", "target": 2, "object_id": obj.id})

        result = engine.world.execute_action(
            1, {"action": "take", "target": 2, "object_id": obj.id}
        )

        assert result.ok
        assert engine.world.inventory(1) == (obj.id,)
        assert engine.world.inventory(2) == ()

    def test_give_requires_carrying_and_adjacency(self):
        engine, first, second, obj = _pair()
        engine.spawn_agent(Agent(agent_id=3, policy=WanderPolicy()), Position(1, 1))

        not_carried = engine.world.execute_action(
            2, {"action": "give", "target": 1, "object_id": obj.id}
        )
        out_of_reach = engine.world.execute_action(
            1, {"action": "give", "target": 3, "object_id": obj.id}
        )
        self_target = engine.world.execute_action(
            1, {"action": "give", "target": 1, "object_id": obj.id}
        )

        assert not_carried.reason == "not_carrying"
        assert out_of_reach.reason == "target_out_of_reach"
        assert self_target.reason == "cannot_target_self"
        assert engine.world.inventory(1) == (obj.id,)  # nothing moved

    def test_give_resources(self):
        engine, first, second, obj = _pair()
        engine.world.credit_resource(1, "wood", 3)

        result = engine.world.execute_action(
            1, {"action": "give", "target": 2, "resource": "wood", "amount": 2}
        )

        assert result.ok
        assert engine.world.resource_count(1, "wood") == 1
        assert engine.world.resource_count(2, "wood") == 2
        transfer = [e for e in engine.world.events if e.type == EventTypes.TRANSFER][-1]
        assert transfer.payload == {
            "kind": "give", "what": "resource", "resource": "wood", "amount": 2,
        }


class TestTrade:
    def test_atomic_swap_of_objects(self):
        engine, first, second, obj = _pair()
        other = engine.world.place_object("stone", Position(6, 4), properties={"quantity": 1})
        picked = engine.world.execute_action(2, {"action": "pick_up", "object_id": other.id})
        assert picked.ok, "fixture: agent 2 should hold the stone"
        assert engine.world.inventory(2) == (other.id,)

        result = engine.world.execute_action(
            1,
            {"action": "trade", "target": 2,
             "give": {"object_id": obj.id}, "want": {"object_id": other.id}},
        )

        assert result.ok
        assert engine.world.inventory(1) == (other.id,)
        assert engine.world.inventory(2) == (obj.id,)

    def test_a_failed_trade_moves_nothing(self):
        engine, first, second, obj = _pair()

        result = engine.world.execute_action(
            1,
            {"action": "trade", "target": 2,
             "give": {"object_id": obj.id}, "want": {"object_id": 999}},
        )

        assert not result.ok
        assert result.reason == "trade_target_lacks_object"
        assert engine.world.inventory(1) == (obj.id,)
        assert engine.world.inventory(2) == ()

    def test_mixed_trade_object_for_resource(self):
        engine, first, second, obj = _pair()
        engine.world.credit_resource(2, "stone", 2)

        result = engine.world.execute_action(
            1,
            {"action": "trade", "target": 2,
             "give": {"object_id": obj.id}, "want": {"resource": "stone", "amount": 2}},
        )

        assert result.ok
        assert engine.world.inventory(1) == ()
        assert engine.world.inventory(2) == (obj.id,)
        assert engine.world.resource_count(1, "stone") == 2
        assert engine.world.resource_count(2, "stone") == 0

    def test_insufficient_offer_is_rejected(self):
        engine, first, second, obj = _pair()
        result = engine.world.execute_action(
            1,
            {"action": "trade", "target": 2,
             "give": {"resource": "wood", "amount": 5}, "want": {"object_id": obj.id}},
        )
        assert not result.ok
        # Both legs are validated before either moves; the wanted
        # object is not on the target, so nothing changes hands.
        assert result.reason == "trade_target_lacks_object"

    def test_a_worthless_offer_is_rejected_before_the_swap(self):
        # An offer that exists, but for a resource the trader lacks.
        engine, first, second, obj = _pair()
        engine.world.credit_resource(2, "wood", 1)
        result = engine.world.execute_action(
            1,
            {"action": "trade", "target": 2,
             "give": {"resource": "wood", "amount": 1},
             "want": {"resource": "wood", "amount": 1}},
        )
        assert not result.ok
        assert result.reason == "trade_self_lacks_resource"
        assert engine.world.resource_count(1, "wood") == 0
        assert engine.world.resource_count(2, "wood") == 1


class TestFollow:
    def test_follow_walks_the_follower_to_the_target(self):
        engine = Engine(_flat())
        world = engine.world
        leader = Agent(agent_id=1, policy=WanderPolicy())
        follower = Agent(agent_id=2, policy=WanderPolicy())
        engine.spawn_agent(leader, Position(4, 4))
        engine.spawn_agent(follower, Position(5, 4))

        started = world.execute_action(2, {"action": "follow", "target": 1})
        assert started.ok

        engine.run(6)  # the leader wanders; the follower closes in

        assert world.follow_target(2) == 1
        distance = abs(follower.position.x - leader.position.x) + abs(
            follower.position.y - leader.position.y
        )
        assert distance <= 1  # it caught up

    def test_following_overrides_cognition(self):
        engine = Engine(_flat())
        world = engine.world
        leader = Agent(agent_id=1, policy=WanderPolicy())
        follower = Agent(agent_id=2, policy=WanderPolicy())
        engine.spawn_agent(leader, Position(4, 4))
        engine.spawn_agent(follower, Position(5, 4))
        world.execute_action(2, {"action": "follow", "target": 1})

        engine.step()

        events = [e for e in world.events if e.type == EventTypes.FOLLOW]
        assert events and events[0].payload == {"kind": "started"}
        # The follower's move is the engine's, not its policy's.
        assert follower.position.x < 5

    def test_unfollow_restores_autonomy(self):
        engine = Engine(_flat())
        world = engine.world
        leader = Agent(agent_id=1, policy=WanderPolicy())
        follower = Agent(agent_id=2, policy=WanderPolicy())
        engine.spawn_agent(leader, Position(4, 4))
        engine.spawn_agent(follower, Position(5, 4))
        world.execute_action(2, {"action": "follow", "target": 1})

        stopped = world.execute_action(2, {"action": "unfollow"})

        assert stopped.ok
        assert world.follow_target(2) is None
        events = [e for e in world.events if e.type == EventTypes.FOLLOW]
        assert events[-1].payload == {"kind": "stopped"}
        again = world.execute_action(2, {"action": "unfollow"})
        assert not again.ok and again.reason == "not_following"

    def test_follow_requires_adjacency(self):
        engine = Engine(_flat())
        world = engine.world
        engine.spawn_agent(Agent(agent_id=1, policy=WanderPolicy()), Position(1, 1))
        engine.spawn_agent(Agent(agent_id=2, policy=WanderPolicy()), Position(7, 7))
        result = world.execute_action(2, {"action": "follow", "target": 1})
        assert not result.ok and result.reason == "target_out_of_reach"
