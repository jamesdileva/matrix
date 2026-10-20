"""Civilization challenges (S44): measurable goals for a living world.

A challenge is a world fact with an explicit metric, not a script. The
world is asked to do something — bridge a river, found a village, bank
stores, survive a winter, invent a game, find a hidden place — and every
tick the tracker reads the answer out of the world itself:

- **bridge**: walkable planks laid on each cell of a water span.
- **settlement**: the largest settlement reaches the member target.
- **transport**: stored resources rise by the target over the baseline.
- **winter**: people remain alive when the next spring arrives.
- **game**: a new game is proposed after the challenge begins.
- **discovery**: any entity enters a hidden region.

Nothing here keeps its own clock or RNG. Metrics are derived from
structures, settlements, storage, seasons, games, and positions, so a
restored world continues the same challenge from the same facts. The
completion rule is data (`completion`) beside the metric, which is what
makes a verdict explainable after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.simulation.ecosystem import SEASONS, season_for
from app.simulation.geometry import Position

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.simulation.world import World

CHALLENGE_KINDS = (
    "bridge",
    "settlement",
    "transport",
    "winter",
    "game",
    "discovery",
)
BRIDGE_MAX_SPAN = 8
DISCOVERY_RADIUS = 2
DEFAULT_SETTLEMENT_MEMBERS = 2
DEFAULT_TRANSPORT_UNITS = 6
DEFAULT_SURVIVORS = 1
DEFAULT_GAMES = 1
DEFAULT_DISCOVERIES = 1

CHALLENGE_CATALOG: dict[str, dict] = {
    "bridge": {
        "name": "Build a bridge",
        "description": "Cross a water span with a walkable plank path.",
        "completion": "every cell of the chosen water span holds a bridge plank",
        "unit": "planks",
        "default_target": None,  # the span's length
        "requires": "a water span of 1-8 cells bounded by floor",
    },
    "settlement": {
        "name": "Establish a settlement",
        "description": "Found a community and gather people into it.",
        "completion": "one settlement has at least the target number of members",
        "unit": "members",
        "default_target": DEFAULT_SETTLEMENT_MEMBERS,
        "requires": "a structure to found on and people to join",
    },
    "transport": {
        "name": "Transport resources",
        "description": "Move goods into a settlement's shared storage.",
        "completion": "stored resources rise by the target over the baseline",
        "unit": "units",
        "default_target": DEFAULT_TRANSPORT_UNITS,
        "requires": "a settlement with storage",
    },
    "winter": {
        "name": "Survive a simulated winter",
        "description": "Keep people alive until the next spring.",
        "completion": "at least the target survivors remain when spring returns",
        "unit": "survivors",
        "default_target": DEFAULT_SURVIVORS,
        "requires": "an ecosystem world with at least one person",
    },
    "game": {
        "name": "Invent a game",
        "description": "Put a new playable game on the table.",
        "completion": "a game is proposed after the challenge begins",
        "unit": "games",
        "default_target": DEFAULT_GAMES,
        "requires": "someone able to propose rules",
    },
    "discovery": {
        "name": "Discover a hidden region",
        "description": "Find a place no one has been shown yet.",
        "completion": "any entity enters the hidden region's radius",
        "unit": "region",
        "default_target": DEFAULT_DISCOVERIES,
        "requires": "at least one explorer",
    },
}


def challenge_catalog() -> dict:
    """The challenge shelf, as data: metrics, rules, and requirements."""
    return {
        "kinds": list(CHALLENGE_KINDS),
        "challenges": {
            kind: dict(CHALLENGE_CATALOG[kind]) for kind in CHALLENGE_KINDS
        },
    }


def _next_spring(tick: int, season_length: int) -> int:
    """The first tick strictly after now on which spring begins."""
    index = SEASONS.index(season_for(tick, season_length))
    seasons_ahead = (-index) % len(SEASONS) or len(SEASONS)
    return (tick // season_length + seasons_ahead) * season_length


def _pick_bridge_span(world: "World", max_span: int = BRIDGE_MAX_SPAN) -> dict:
    """Find a deterministic water span bounded by floor on both sides.

    Horizontal spans are preferred (lower rows first), then vertical;
    the first qualifying run wins. The challenge's target is the span's
    length, so completion is simply "every cell planked".
    """

    def water(position: Position) -> bool:
        return world.terrain_at(position).value == "water"

    for y in range(1, world.height - 1):
        x = 1
        while x < world.width - 1:
            if not water(Position(x, y)):
                x += 1
                continue
            start = x
            while x < world.width - 1 and water(Position(x, y)):
                x += 1
            end = x - 1
            length = end - start + 1
            if (
                1 <= length <= max_span
                and world.is_floor(Position(start - 1, y))
                and world.is_floor(Position(end + 1, y))
            ):
                return {
                    "axis": "horizontal",
                    "cells": [
                        Position(cell_x, y).to_dict()
                        for cell_x in range(start, end + 1)
                    ],
                    "shores": [
                        Position(start - 1, y).to_dict(),
                        Position(end + 1, y).to_dict(),
                    ],
                    "length": length,
                }

    for x in range(1, world.width - 1):
        y = 1
        while y < world.height - 1:
            if not water(Position(x, y)):
                y += 1
                continue
            start = y
            while y < world.height - 1 and water(Position(x, y)):
                y += 1
            end = y - 1
            length = end - start + 1
            if (
                1 <= length <= max_span
                and world.is_floor(Position(x, start - 1))
                and world.is_floor(Position(x, end + 1))
            ):
                return {
                    "axis": "vertical",
                    "cells": [
                        Position(x, cell_y).to_dict()
                        for cell_y in range(start, end + 1)
                    ],
                    "shores": [
                        Position(x, start - 1).to_dict(),
                        Position(x, end + 1).to_dict(),
                    ],
                    "length": length,
                }
    raise ValueError("no water span 1-8 cells wide with floor on both shores")


def _hidden_region(world: "World", radius: int = DISCOVERY_RADIUS) -> dict:
    """Choose the floor cell farthest from everyone, deterministically."""
    positions = list(world.entity_positions().values())
    if not positions:
        raise ValueError("a discovery challenge needs someone to explore")
    best: Position | None = None
    best_key: tuple[int, int, int] | None = None
    for y in range(world.height):
        for x in range(world.width):
            cell = Position(x, y)
            if not world.is_floor(cell):
                continue
            distance = min(
                abs(cell.x - position.x) + abs(cell.y - position.y)
                for position in positions
            )
            key = (-distance, y, x)
            if best_key is None or key < best_key:
                best, best_key = cell, key
    if best is None:
        raise ValueError("no floor to hide a region in")
    return {"center": best.to_dict(), "radius": radius}


def _total_storage(world: "World") -> int:
    return sum(
        sum(settlement.storage.values()) for settlement in world.settlements
    )


@dataclass
class Challenge:
    """One measurable ask, its metric, and its verdict."""

    id: int
    kind: str
    name: str
    description: str
    completion: str
    target: int
    status: str = "active"
    started_tick: int = 0
    completed_tick: int | None = None
    failed_reason: str | None = None
    metrics: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    def to_dict(self, *, reveal: bool = True) -> dict:
        details = dict(self.details)
        if self.kind == "discovery" and self.status != "completed" and not reveal:
            details = {"hidden": True}
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "completion": self.completion,
            "status": self.status,
            "target": self.target,
            "started_tick": self.started_tick,
            "completed_tick": self.completed_tick,
            "failed_reason": self.failed_reason,
            "metrics": dict(self.metrics),
            "details": details,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Challenge":
        kind = data.get("kind")
        if kind not in CHALLENGE_CATALOG:
            raise ValueError(f"unknown challenge kind {kind!r}")
        spec = CHALLENGE_CATALOG[kind]
        target = data.get("target", spec["default_target"] or 1)
        if not isinstance(target, int) or isinstance(target, bool) or target < 1:
            target = spec["default_target"] or 1
        status = data.get("status", "active")
        if status not in ("active", "completed", "failed"):
            status = "active"
        completed_tick = data.get("completed_tick")
        if not isinstance(completed_tick, int) or isinstance(completed_tick, bool):
            completed_tick = None
        metrics = data.get("metrics")
        details = data.get("details")
        return cls(
            id=int(data["id"]),
            kind=kind,
            name=str(data.get("name") or spec["name"]),
            description=str(data.get("description") or spec["description"]),
            completion=str(data.get("completion") or spec["completion"]),
            target=target,
            status=status,
            started_tick=int(data.get("started_tick", 0)),
            completed_tick=completed_tick,
            failed_reason=(
                data.get("failed_reason")
                if isinstance(data.get("failed_reason"), str)
                else None
            ),
            metrics=dict(metrics) if isinstance(metrics, dict) else {},
            details=dict(details) if isinstance(details, dict) else {},
        )

    def advance(self, world: "World") -> str | None:
        """Refresh metrics; return "completed"/"failed" on a verdict."""
        if self.status != "active":
            return None
        handler = getattr(self, f"_advance_{self.kind}")
        return handler(world)

    def _finish(self, world: "World", status: str, reason: str | None = None) -> str:
        self.status = status
        self.completed_tick = world.tick
        self.failed_reason = reason
        return status

    def _advance_bridge(self, world: "World") -> str | None:
        planks = 0
        for cell in self.details.get("cells", []):
            obj = world.object_at(Position.from_dict(cell))
            if obj is not None and obj.properties.get("bridge"):
                planks += 1
        self.metrics = {
            "value": planks,
            "target": self.target,
            "unit": "planks",
        }
        if planks >= self.target:
            return self._finish(world, "completed")
        return None

    def _advance_settlement(self, world: "World") -> str | None:
        settlements = world.settlements
        members = max((len(settlement.members) for settlement in settlements), default=0)
        self.metrics = {
            "value": members,
            "target": self.target,
            "unit": "members",
            "settlements": len(settlements),
            "homes": sum(len(settlement.home_ids) for settlement in settlements),
            "storage": _total_storage(world),
        }
        if members >= self.target:
            return self._finish(world, "completed")
        return None

    def _advance_transport(self, world: "World") -> str | None:
        baseline = self.details.get("baseline", 0)
        stored = _total_storage(world)
        delivered = max(0, stored - baseline)
        self.metrics = {
            "value": delivered,
            "target": self.target,
            "unit": "units",
            "storage": stored,
            "baseline": baseline,
        }
        if delivered >= self.target:
            return self._finish(world, "completed")
        return None

    def _advance_winter(self, world: "World") -> str | None:
        ecosystem = world.ecosystem
        if ecosystem is None:  # pragma: no cover - enabled at start
            return self._finish(world, "failed", "the ecosystem is gone")
        survivors = len(world.entity_ids)
        deadline = int(self.details.get("deadline_tick", world.tick))
        self.metrics = {
            "value": survivors,
            "target": self.target,
            "unit": "survivors",
            "season": season_for(world.tick, ecosystem.season_length),
            "ticks_remaining": max(0, deadline - world.tick),
        }
        if survivors == 0:
            return self._finish(world, "failed", "no one survived")
        if world.tick >= deadline:
            if survivors >= self.target:
                return self._finish(world, "completed")
            return self._finish(
                world,
                "failed",
                f"only {survivors} survived, {self.target} needed",
            )
        return None

    def _advance_game(self, world: "World") -> str | None:
        baseline = self.details.get("baseline", 0)
        invented = max(0, len(world.games) - baseline)
        self.metrics = {
            "value": invented,
            "target": self.target,
            "unit": "games",
        }
        if invented >= self.target:
            return self._finish(world, "completed")
        return None

    def _advance_discovery(self, world: "World") -> str | None:
        center_data = self.details.get("center")
        if not isinstance(center_data, dict):
            return self._finish(world, "failed", "the hidden region was lost")
        center = Position.from_dict(center_data)
        radius = int(self.details.get("radius", DISCOVERY_RADIUS))
        distances = [
            abs(position.x - center.x) + abs(position.y - center.y)
            for position in world.entity_positions().values()
        ]
        nearest = min(distances, default=None)
        found = nearest is not None and nearest <= radius
        self.metrics = {
            "value": 1 if found else 0,
            "target": self.target,
            "unit": "region",
            "distance": nearest,
        }
        if found:
            return self._finish(world, "completed")
        return None


def build_challenge(
    world: "World",
    kind: str,
    *,
    target: int | None = None,
    name: str | None = None,
    challenge_id: int = 1,
) -> Challenge:
    """Construct and configure one challenge from the world's facts."""
    if kind not in CHALLENGE_CATALOG:
        raise ValueError(
            f"unknown challenge {kind!r}; expected one of {list(CHALLENGE_KINDS)}"
        )
    if target is not None and (
        not isinstance(target, int) or isinstance(target, bool) or target < 1
    ):
        raise ValueError(f"target must be a positive integer, got {target!r}")
    spec = CHALLENGE_CATALOG[kind]
    details: dict = {}
    target = target if target is not None else spec["default_target"] or 1

    if kind == "bridge":
        details = _pick_bridge_span(world)
        target = details["length"]
    elif kind == "transport":
        details = {"baseline": _total_storage(world)}
    elif kind == "winter":
        ecosystem = world.ecosystem
        if ecosystem is None:
            raise ValueError("winter challenges need an ecosystem")
        if not world.entity_ids:
            raise ValueError("winter challenges need at least one person")
        details = {
            "start_agents": len(world.entity_ids),
            "start_season": season_for(world.tick, ecosystem.season_length),
            "deadline_tick": _next_spring(world.tick, ecosystem.season_length),
        }
    elif kind == "game":
        details = {"baseline": len(world.games)}
    elif kind == "discovery":
        details = _hidden_region(world)

    label = (name or spec["name"]).strip()
    if not label:
        raise ValueError("a challenge needs a name")
    return Challenge(
        id=challenge_id,
        kind=kind,
        name=label,
        description=spec["description"],
        completion=spec["completion"],
        target=target,
        started_tick=world.tick,
        metrics={"value": 0, "target": target, "unit": spec["unit"]},
        details=details,
    )
