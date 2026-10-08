import pytest

from app.models.decision import Decision, DecisionError, parse_decision


class TestValidDecisions:
    def test_parses_engine_contract(self):
        decision = parse_decision('{"action": {"action": "move", "direction": "north"}}')
        assert decision.action == {"action": "move", "direction": "north"}
        assert decision.goal_update is None
        assert decision.as_dict() == {"action": {"action": "move", "direction": "north"}}

    def test_parses_guide_type_shape_and_normalizes(self):
        # Guide §7 spells the verb "type"; the engine contract says
        # "action". Both must land on the engine shape.
        decision = parse_decision('{"action": {"type": "move", "direction": "north"}}')
        assert decision.action == {"action": "move", "direction": "north"}
        assert "type" not in decision.action

    def test_accepts_already_parsed_dict(self):
        decision = parse_decision({"action": {"action": "pick_up", "object_id": 3}})
        assert decision.action == {"action": "pick_up", "object_id": 3}

    def test_strips_markdown_fences_and_surrounding_prose(self):
        raw = (
            "Sure, here you go:\n"
            '```json\n{"action": {"action": "look"}}\n```\n'
            "Hope that helps!"
        )
        decision = parse_decision(raw)
        assert decision.action == {"action": "look"}

    def test_optional_string_fields_kept(self):
        decision = parse_decision(
            '{"action": {"action": "look"}, "goal_update": "find food",'
            ' "thought_summary": "nothing to do", "message": "hello"}'
        )
        assert decision.goal_update == "find food"
        assert decision.thought_summary == "nothing to do"
        assert decision.message == "hello"
        assert decision.as_dict()["goal_update"] == "find food"

    def test_wrong_typed_optional_fields_dropped_not_rejected(self):
        decision = parse_decision(
            '{"action": {"action": "look"}, "goal_update": 42, "thought_summary": ["x"]}'
        )
        assert decision.goal_update is None
        assert decision.thought_summary is None

    def test_unknown_keys_ignored(self):
        decision = parse_decision('{"action": {"action": "look"}, "confidence": 0.9}')
        assert decision.action == {"action": "look"}

    def test_as_dict_omits_absent_optionals(self):
        assert parse_decision('{"action": {"action": "look"}}').as_dict() == {
            "action": {"action": "look"}
        }


class TestRejectedOutput:
    @pytest.mark.parametrize(
        "raw,reason",
        [
            ("I cannot comply.", "not_json"),
            ("", "not_json"),
            ("```json\nnot json at all\n```", "not_json"),
            ("[1, 2, 3]", "not_object"),
            ("42", "not_object"),
            ('{"goal_update": "x"}', "missing_action"),
            ('{"action": "move"}', "action_not_object"),
            ('{"action": {}}', "invalid_verb"),
            ('{"action": {"action": ""}}', "invalid_verb"),
            ('{"action": {"action": 5}}', "invalid_verb"),
            ('{"action": {"type": null}}', "invalid_verb"),
        ],
    )
    def test_rejected_with_reason(self, raw, reason):
        with pytest.raises(DecisionError) as excinfo:
            parse_decision(raw)
        assert excinfo.value.reason == reason

    def test_unsupported_input_type(self):
        with pytest.raises(DecisionError):
            parse_decision(None)
        with pytest.raises(DecisionError):
            parse_decision(42)


class TestDecision:
    def test_decision_is_immutable(self):
        decision = Decision(action={"action": "look"})
        with pytest.raises(Exception):
            decision.action = {}
