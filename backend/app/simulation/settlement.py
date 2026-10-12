"""Settlements: persistent communities in the Void (S30).

A settlement is what a population builds when it stops moving. It has
an identity (a name, a founder, the population it belongs to), homes
(structures adopted around its centre), shared storage (a ledger any
member can bank into and draw from), roads (recorded paths that carry
no blocking — a road you cannot walk is not a road), and resource
zones: the first property rule in the Void, where a claimed source
refuses outsiders.

Settlements are world facts, like structures and teams: the world
owns the registry, every change rides the timeline, and nothing is
stored state that could disagree with the world it describes. A
structure joins a settlement either by adoption (a member claims it
explicitly) or by being raised inside the settlement's extent by one
of its members — a population that builds together grows a village
without being told to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.simulation.geometry import Position

# How far from a settlement's centre its members' building counts as
# part of it (Manhattan cells). Small on purpose: a settlement is a
# village, not a continent.
SETTLEMENT_EXTENT = 12

# What a purpose on an adopted structure means to the settlement.
PURPOSE_HOME = "home"
PURPOSE_STORAGE = "storage"

ROLE_FOUNDER = "founder"
ROLE_MEMBER = "member"


@dataclass
class Settlement:
    """One persistent community: identity, members, and what it holds."""

    id: int
    name: str
    founder_id: int
    population_id: int | None
    founded_tick: int
    center: Position
    members: set[int] = field(default_factory=set)
    home_ids: list[int] = field(default_factory=list)
    storage_ids: list[int] = field(default_factory=list)
    zones: dict[int, str] = field(default_factory=dict)  # object id -> resource kind
    storage: dict[str, int] = field(default_factory=dict)  # the shared ledger
    road_ids: list[int] = field(default_factory=list)

    def is_member(self, entity_id: int) -> bool:
        return entity_id in self.members

    def role_of(self, entity_id: int) -> str | None:
        if entity_id == self.founder_id:
            return ROLE_FOUNDER
        if entity_id in self.members:
            return ROLE_MEMBER
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "founder_id": self.founder_id,
            "population_id": self.population_id,
            "founded_tick": self.founded_tick,
            "center": self.center.to_dict(),
            "members": sorted(self.members),
            "home_ids": list(self.home_ids),
            "storage_ids": list(self.storage_ids),
            "road_ids": list(self.road_ids),
            "zones": [
                {"object_id": object_id, "resource": kind}
                for object_id, kind in sorted(self.zones.items())
            ],
            "storage": dict(self.storage),
        }


@dataclass
class Road:
    """A paved path: cells on the ground, blocking nothing."""

    id: int
    settlement_id: int
    owner_id: int
    cells: list[Position] = field(default_factory=list)
    created_tick: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "settlement_id": self.settlement_id,
            "owner_id": self.owner_id,
            "cells": [cell.to_dict() for cell in self.cells],
            "created_tick": self.created_tick,
        }
