"""Scripted policies: deterministic decision strategies.

No model calls — these exist to populate the Void before intelligence
arrives (S08) and to test the environment independently of model
behaviour (guide §30's scripted agents grow from here). All of them are
pure functions of the observation.
"""

from __future__ import annotations

DEFAULT_ORDER = ("north", "east", "south", "west")


class AlwaysMoveNorthPolicy:
    """The simplest possible mind: one direction, forever."""

    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "move", "direction": "north"}}


class WanderPolicy:
    """Walk in the first legal direction of a fixed order; look when stuck."""

    def __init__(self, order: tuple[str, ...] = DEFAULT_ORDER) -> None:
        self.order = order

    def decide(self, observation: dict) -> dict:
        cells = {c["direction"]: c for c in observation["cells"]}
        for direction in self.order:
            cell = cells.get(direction, {})
            if self._walkable(cell):
                return {"action": {"action": "move", "direction": direction}}
        return {"action": {"action": "look"}}

    @staticmethod
    def _walkable(cell: dict) -> bool:
        return cell.get("terrain") == "floor" and "object" not in cell and "entity" not in cell


class ForagerPolicy:
    """Pick up anything within reach; step toward the nearest visible
    object; wander otherwise.

    Greedy and short-sighted on purpose: it only knows its observation —
    no pathfinding, no memory. Good enough to demonstrate object
    interaction, and deterministic end to end.
    """

    def __init__(self, order: tuple[str, ...] = DEFAULT_ORDER) -> None:
        self.order = order
        self._wander = WanderPolicy(order)

    def decide(self, observation: dict) -> dict:
        cells = {c["direction"]: c for c in observation["cells"]}

        for direction, cell in cells.items():
            if direction != "here" and "object" in cell and cell.get("terrain") == "floor":
                return {"action": {"action": "pick_up", "object_id": cell["object"]["id"]}}

        objects = [n for n in observation["nearby"] if n["kind"] == "object"]
        if objects:
            target = objects[0]  # nearest (sorted by distance, then id)
            dx = target["position"]["x"] - observation["self"]["position"]["x"]
            dy = target["position"]["y"] - observation["self"]["position"]["y"]
            for direction in _step_options(dx, dy):
                if self._wander._walkable(cells.get(direction, {})):
                    return {"action": {"action": "move", "direction": direction}}

        return self._wander.decide(observation)


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
