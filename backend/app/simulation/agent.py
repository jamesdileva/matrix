"""Agents: the inhabitants of the Void.

An Agent is a thin actor over the action contract. It owns no world state
— its position, inventory and history live in the World — and it never
mutates the world except through ``world.execute_action``. What
distinguishes one agent from another is its policy: a function from
observation to a decision. Scripted policies today; model-driven
decisions in S08 through the same contract.

Scripted policies must be stateless functions of the observation —
determinism of the whole simulation rests on decisions being pure. Model
policies (S08) cannot be pure (an LLM is not deterministic); they are
confined to ``ModelPolicy``, which is fed asynchronously and stores a
snapshot, and the world re-validates every action they propose, so a
surprising brain costs a rejected action, never corruption.

An agent's own state — goal and short memory — rides along inside the
observation (guide §6's precedent: current_goal), because a decision
that cannot see what just happened cannot learn from it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Protocol

from app.simulation.actions import DIRECTIONS, ActionResult
from app.simulation.inheritance import InheritancePackage
from app.simulation.memory import AgentMemory
from app.simulation.world import Position, World


class Policy(Protocol):
    """A decision strategy: observation -> decision dict.

    Decision shape (implementation guide §7, shared with the future LLM
    contract):

        {"action": {...action proposal...},
         "goal_update": str | None}          # optional

    "thought_summary"/"message" may appear once minds can produce them;
    the Agent ignores keys it does not know.
    """

    def decide(self, observation: dict) -> dict: ...


@dataclass
class Agent:
    agent_id: int
    policy: Policy
    observation_radius: int = 2
    goal: str | None = None
    status: str = "created"  # created -> alive
    # Lineage (S09): None for the founding generation, set by
    # Engine.create_child for everyone after. The engine assigns
    # these; the database persists them as global ids.
    parent_id: int | None = None
    generation: int = 0
    population_id: int | None = None
    # Inheritance (S10): what this agent received at birth, and what it
    # currently intends to pass on. The intent is declared by a
    # decision's ``inheritance`` field; create_child uses it by
    # default. Both are deep-copied on the way in and out.
    traits: dict = field(default_factory=dict)
    knowledge: list = field(default_factory=list)
    cultural_artifacts: list = field(default_factory=list)
    inheritance_received: dict | None = None
    pending_inheritance: dict | None = None
    # Short memory of recent action outcomes. Agent state, like the
    # goal — folded into the observation (guide §6's precedent:
    # current_goal), because a decision that cannot see what just
    # happened cannot learn from it.
    memory: AgentMemory = field(default_factory=AgentMemory)
    _world: World | None = field(default=None, repr=False, compare=False)

    def spawn(self, world: World, position: Position) -> None:
        """Enter the world. The world validates the cell; failures raise."""
        if self.status == "alive":
            raise RuntimeError(f"agent {self.agent_id} is already alive")
        world.add_entity(self.agent_id, position)
        self._world = world
        self.status = "alive"

    @property
    def position(self) -> Position | None:
        return self._world.entity_position(self.agent_id) if self._world else None

    # ------------------------------------------------------------------
    # Lifecycle phases (implementation guide §7): observe -> decide -> act
    # ------------------------------------------------------------------

    def observe(self) -> dict:
        """Bounded, radius-limited view of the world.

        Observation is sensing, not acting: it records no events and is
        free. ``nearby`` is bounded by ``observation_radius``; the
        movement ``cells`` are always the immediate neighbourhood.
        The whole world is never included.
        """
        if self._world is None or self.status != "alive":
            raise RuntimeError(f"agent {self.agent_id} is not alive; spawn it first")
        world = self._world
        position = world.entity_position(self.agent_id)
        if position is None:  # pragma: no cover - status and registry agree
            raise RuntimeError(f"agent {self.agent_id} has no position")

        cells = []
        for name, (dx, dy) in [("here", (0, 0))] + list(DIRECTIONS.items()):
            cell_pos = Position(position.x + dx, position.y + dy)
            cell: dict = {"direction": name, "position": cell_pos.to_dict()}
            if not world.in_bounds(cell_pos):
                cell["terrain"] = "void"
            else:
                cell["terrain"] = world.terrain_at(cell_pos).value
                obj = world.object_at(cell_pos)
                if obj is not None:
                    cell["object"] = {"id": obj.id, "type": obj.type}
                entity = world.entity_at(cell_pos)
                if entity is not None and entity != self.agent_id:
                    cell["entity"] = entity
            cells.append(cell)

        radius = self.observation_radius
        nearby = []
        for y in range(position.y - radius, position.y + radius + 1):
            for x in range(position.x - radius, position.x + radius + 1):
                cell_pos = Position(x, y)
                if cell_pos == position or not world.in_bounds(cell_pos):
                    continue
                distance = abs(x - position.x) + abs(y - position.y)
                obj = world.object_at(cell_pos)
                if obj is not None:
                    nearby.append(
                        {"kind": "object", "id": obj.id, "type": obj.type,
                         "position": cell_pos.to_dict(), "distance": distance}
                    )
                entity = world.entity_at(cell_pos)
                if entity is not None:
                    nearby.append(
                        {"kind": "entity", "id": entity,
                         "position": cell_pos.to_dict(), "distance": distance}
                    )
        nearby.sort(key=lambda n: (n["distance"], n["kind"], n["id"]))

        return {
            "self": {
                "id": self.agent_id,
                "position": position.to_dict(),
                "tick": world.tick,
                "goal": self.goal,
            },
            "cells": cells,
            "nearby": nearby,
            "inventory": list(world.inventory(self.agent_id)),
            "memory": self.memory.recent(),
            # Inherited culture (S10): the agent sees what it received
            # at birth, because deciding what to pass onward requires
            # knowing what was passed to you (guide §11).
            "traits": copy.deepcopy(self.traits),
            "knowledge": list(self.knowledge),
            "cultural_artifacts": list(self.cultural_artifacts),
            "messages": [],  # communication arrives in later sprints
        }

    def decide(self) -> dict:
        return self.policy.decide(self.observe())

    def act(self) -> ActionResult:
        """One cognition cycle: observe, decide, propose the action.

        The world still decides everything — a broken or illegal decision
        comes back as a rejected ActionResult and the agent lives on.
        The outcome (and the goal it was pursuing) is remembered, so the
        next decision can see what just happened.

        A decision may also declare the inheritance this agent intends to
        pass to its next child (S10); that intent is stored and used by
        ``Engine.create_child`` unless an explicit package is given.
        """
        decision = self.decide()
        if not isinstance(decision, dict):
            decision = {}
        goal_update = decision.get("goal_update")
        if goal_update is not None:
            self.goal = goal_update
        intent = decision.get("inheritance")
        if isinstance(intent, dict):
            self.pending_inheritance = copy.deepcopy(intent)
        action = decision.get("action")
        result = self._world.execute_action(self.agent_id, action)
        self.memory.remember_action(
            tick=self._world.tick,
            action=result.action,
            ok=result.ok,
            reason=result.reason,
            goal=self.goal,
        )
        return result
