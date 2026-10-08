"""S08 — short memory: the agent's bounded ring of recent outcomes."""

import json

from app.simulation.memory import DEFAULT_MEMORY_LIMIT, AgentMemory


class TestAgentMemory:
    def test_remembers_entries_in_order(self):
        memory = AgentMemory(limit=3)
        for tick in range(3):
            memory.remember_action(
                tick=tick,
                action={"action": "look"},
                ok=True,
                reason=None,
                goal=None,
            )
        assert [entry["tick"] for entry in memory.recent()] == [0, 1, 2]

    def test_bounded_evicts_oldest(self):
        memory = AgentMemory(limit=DEFAULT_MEMORY_LIMIT)
        for tick in range(DEFAULT_MEMORY_LIMIT + 5):
            memory.remember({"tick": tick})
        entries = memory.recent()
        assert len(entries) == DEFAULT_MEMORY_LIMIT
        assert entries[0]["tick"] == 5
        assert entries[-1]["tick"] == DEFAULT_MEMORY_LIMIT + 4
        assert len(memory) == DEFAULT_MEMORY_LIMIT

    def test_recent_count_subset(self):
        memory = AgentMemory(limit=8)
        for tick in range(4):
            memory.remember({"tick": tick})
        assert [entry["tick"] for entry in memory.recent(2)] == [2, 3]

    def test_entries_are_json_serializable(self):
        memory = AgentMemory()
        memory.remember_action(
            tick=3,
            action={"action": "pick_up", "object_id": 7},
            ok=False,
            reason="out_of_reach",
            goal="find food",
        )
        # Model requests and logged events both serialize memory.
        assert json.loads(json.dumps(memory.recent())) == memory.recent()

    def test_copies_defend_against_mutation(self):
        memory = AgentMemory()
        memory.remember({"tick": 1, "action": {"action": "look"}})
        snapshot = memory.recent()
        snapshot[0]["action"]["action"] = "move"
        assert memory.recent()[0]["action"]["action"] == "look"

    def test_clear(self):
        memory = AgentMemory()
        memory.remember({"tick": 1})
        memory.clear()
        assert memory.recent() == []
        assert len(memory) == 0
