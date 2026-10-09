"""Scripted policies: deterministic decision strategies.

No model calls — these exist to populate the Void before intelligence
arrives (S08) and to test the environment independently of model
behaviour (guide §30's scripted agents grow from here). All of them are
pure functions of the observation.
"""

from __future__ import annotations

from app.simulation.actions import RESOURCE_SOURCES, WATER_RESOURCE

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


class GathererPolicy:
    """A resource-driven mind (S17): gather what is next to you, walk to
    the nearest source otherwise.

    ``resource`` picks what it is after (``wood``, ``stone``, ``food``,
    or ``water`` — water is gathered from adjacent water terrain, the
    others from their object source). Like the forager, it is greedy
    and short-sighted on purpose: it knows only its observation.
    """

    def __init__(self, resource: str = "wood", order: tuple[str, ...] = DEFAULT_ORDER) -> None:
        if resource not in RESOURCE_SOURCES and resource != WATER_RESOURCE:
            raise ValueError(f"unknown resource {resource!r}")
        self.resource = resource
        self.order = order
        self._wander = WanderPolicy(order)

    def decide(self, observation: dict) -> dict:
        cells = {c["direction"]: c for c in observation["cells"]}

        if self.resource == WATER_RESOURCE:
            if self._water_adjacent(cells):
                return {"action": {"action": "gather", "resource": WATER_RESOURCE}}
        else:
            for direction, cell in cells.items():
                if (
                    direction != "here"
                    and cell.get("object", {}).get("type") == RESOURCE_SOURCES[self.resource]
                    and (cell.get("object", {}).get("quantity") or 0) > 0
                ):
                    return {"action": {"action": "gather", "resource": self.resource}}

        sources = [
            n
            for n in observation.get("nearby", [])
            if n.get("kind") == "object"
            and n.get("type") == RESOURCE_SOURCES.get(self.resource)
            and (n.get("quantity") or 0) > 0
        ]
        if sources:
            target = sources[0]  # nearest (sorted by distance, then id)
            dx = target["position"]["x"] - observation["self"]["position"]["x"]
            dy = target["position"]["y"] - observation["self"]["position"]["y"]
            for direction in _step_options(dx, dy):
                if self._wander._walkable(cells.get(direction, {})):
                    return {"action": {"action": "move", "direction": direction}}

        return {"action": {"action": "move", "direction": self._sweep(cells)}}

    def _sweep(self, cells: dict) -> str:
        """No source in sight: sweep the world, east then north then west.

        A pure function of the observation (the agent's own position
        defines the sweep phase), so the gatherer covers the map
        deterministically instead of pinning itself against the first
        wall it meets — a blind local search on a sparse map finds
        nothing.
        """
        for direction in ("east", "north", "west", "south"):
            if self._wander._walkable(cells.get(direction, {})):
                return direction
        return "look"

    @staticmethod
    def _water_adjacent(cells: dict) -> bool:
        return any(
            cell.get("terrain") == "water"
            for direction, cell in cells.items()
            if direction != "here"
        )
