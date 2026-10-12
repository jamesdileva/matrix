"""The grid's coordinates.

Lives on its own so the world and the things the world holds
(settlements, roads) can share it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(x=data["x"], y=data["y"])
