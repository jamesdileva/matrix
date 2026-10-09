"""Structured decisions: the contract between a brain and the world.

A decision is what a model (or scripted policy) hands back after
observing the world. Two layers own different halves of its validity:

- this module owns *structure*: is the output parseable JSON, does it
  carry a usable action proposal, are the optional fields the right
  type;
- the world owns *rules*: whether the action is legal here and now.
  Unknown verbs and illegal moves come back as rejected actions with
  recorded events (``actions.py``), never as exceptions.

The shape follows the engine's existing contract (``agent.py``):

    {"action": {"action": "move", "direction": "north"},
     "goal_update": "find food",        # optional, str
     "thought_summary": "why",          # optional, str
     "message": null,                   # optional, str | None
     "inheritance": {"traits": ..., "knowledge": [...],
                     "message": ..., "cultural_artifacts": [...]}}
                                         # optional, dict — S10 parent intent

Guide §7 spells the verb as ``{"type": "move"}`` inside the proposal;
that spelling is accepted and normalized to the engine contract so
downstream code (and every existing test) sees one shape.

Rejection policy (roadmap S07: "invalid model output is rejected"): if
no usable decision can be extracted, ``parse_decision`` raises
``DecisionError`` with a machine-readable ``reason`` — the caller falls
back to a safe action, the world is untouched. Wrongly-typed *optional*
string fields are dropped rather than rejected: they are annotation,
never instructions. Unknown top-level keys are ignored, mirroring
``Agent.act``'s tolerance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


class DecisionError(ValueError):
    """The raw output could not be turned into a decision.

    ``reason`` is a short machine-readable code (``not_json``,
    ``missing_action``, ``invalid_verb``, ...) for logs and events.
    """

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(detail or reason)
        self.reason = reason


@dataclass(frozen=True)
class Decision:
    """A validated decision in the engine's contract shape."""

    action: dict  # engine-shape proposal, e.g. {"action": "move", "direction": "north"}
    goal_update: str | None = None
    thought_summary: str | None = None
    message: str | None = None
    # S10: what the agent intends to pass to its next child. Structure
    # is validated here (an object); meaning (traits/knowledge/
    # message/cultural_artifacts) belongs to the engine's
    # InheritancePackage.
    inheritance: dict | None = None

    def as_dict(self) -> dict:
        """The dict an ``Agent`` consumes (``Policy.decide``'s contract)."""
        decision: dict = {"action": dict(self.action)}
        if self.goal_update is not None:
            decision["goal_update"] = self.goal_update
        if self.thought_summary is not None:
            decision["thought_summary"] = self.thought_summary
        if self.message is not None:
            decision["message"] = self.message
        if self.inheritance is not None:
            decision["inheritance"] = self.inheritance
        return decision


def parse_decision(raw: str | dict) -> Decision:
    """Turn raw model output (text or already-parsed JSON) into a Decision.

    Raises ``DecisionError`` when no structurally valid decision can be
    extracted.
    """
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        data = extract_json_object(raw)
    else:
        raise DecisionError("not_json", f"expected text or dict, got {type(raw).__name__}")

    if not isinstance(data, dict):
        raise DecisionError("not_object", "decision must be a JSON object")

    action = data.get("action")
    if action is None:
        raise DecisionError("missing_action", "decision has no 'action'")
    if not isinstance(action, dict):
        raise DecisionError("action_not_object", "'action' must be an object")

    verb = action.get("action") or action.get("type")
    if not isinstance(verb, str) or not verb.strip():
        raise DecisionError("invalid_verb", "action proposal needs a non-empty 'action'/'type' verb")

    proposal = {key: value for key, value in action.items() if key != "type"}
    proposal["action"] = verb

    return Decision(
        action=proposal,
        goal_update=_optional_str(data, "goal_update"),
        thought_summary=_optional_str(data, "thought_summary"),
        message=_optional_str(data, "message"),
        inheritance=_optional_dict(data, "inheritance"),
    )


def _optional_dict(data: dict, key: str) -> dict | None:
    """Optional structured fields: keep objects, drop wrong types."""
    value = data.get(key)
    return value if isinstance(value, dict) else None


def _optional_str(data: dict, key: str) -> str | None:
    """Optional annotation fields: keep strings, drop wrong types."""
    value = data.get(key)
    return value if isinstance(value, str) else None


def extract_json_object(text: str) -> dict:
    """Best-effort JSON object extraction from raw model text.

    Models wrap JSON in markdown fences or surround it with prose; both
    are normal, not grounds for rejection. Tries, in order: the whole
    string (fences stripped), then the outermost ``{...}`` span.

    Public: the S16 word-seed experiment asks models for a different
    JSON shape (concepts + artifact) through the same tolerance rules.
    """
    stripped = _strip_fences(text.strip())
    for candidate in (stripped, _outermost_span(stripped)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
        raise DecisionError("not_object", "decision must be a JSON object")
    raise DecisionError("not_json", "no JSON object found in model output")


def _strip_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]  # drop the opening fence line
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _outermost_span(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
