"""MockProvider: a brain that needs no network.

Deterministic by construction — same observation in, same decision text
out — so tests and headless worlds exercise the *full* provider ->
parser -> decision path with zero I/O. The roadmap's verification
("the mock model works with no network") and the guide's insistence
("a simulation should be able to run without an LLM") both land here.

The behaviour is a copy of the scripted ForagerPolicy's heuristic:
pick up anything in reach, step toward the nearest visible object, else
take the first walkable direction, else look. Not intelligence — proof
that the seam works.
"""

from __future__ import annotations

import json

from app.models.provider import ModelRequest, ModelResponse

_WANDER_ORDER = ("north", "east", "south", "west")


class MockProvider:
    """A deterministic offline provider emitting engine-contract JSON."""

    name = "mock"
    model = "mock-1"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text=json.dumps(_decide(request.observation)),
            provider=self.name,
            model=self.model,
        )


def _decide(observation: dict) -> dict:
    cells = {cell["direction"]: cell for cell in observation.get("cells", [])}

    for direction, cell in cells.items():
        if direction != "here" and "object" in cell and cell.get("terrain") == "floor":
            return {"action": {"action": "pick_up", "object_id": cell["object"]["id"]}}

    objects = [n for n in observation.get("nearby", []) if n.get("kind") == "object"]
    if objects:
        target = objects[0]  # nearest (observation sorts by distance, then id)
        dx = target["position"]["x"] - observation["self"]["position"]["x"]
        dy = target["position"]["y"] - observation["self"]["position"]["y"]
        for direction in _step_options(dx, dy):
            if _walkable(cells.get(direction, {})):
                return {"action": {"action": "move", "direction": direction}}

    for direction in _WANDER_ORDER:
        if _walkable(cells.get(direction, {})):
            return {"action": {"action": "move", "direction": direction}}

    return {"action": {"action": "look"}}


def _walkable(cell: dict) -> bool:
    return (
        cell.get("terrain") == "floor"
        and "object" not in cell
        and "entity" not in cell
    )


def _step_options(dx: int, dy: int) -> tuple[str, ...]:
    """Directions reducing the distance, primary axis first."""
    options: list[str] = []
    if abs(dx) >= abs(dy):
        options += ["east" if dx > 0 else "west"] if dx else []
        options += ["south" if dy > 0 else "north"] if dy else []
    else:
        options += ["south" if dy > 0 else "north"] if dy else []
        options += ["east" if dx > 0 else "west"] if dx else []
    return tuple(options)
