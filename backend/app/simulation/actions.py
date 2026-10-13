"""Action proposals: the only way entities change the world.

An action is a plain dict, e.g. ``{"action": "move", "direction": "north"}``.
The dispatcher validates it against the world's rules and either applies it
or rejects it with a reason. A rejected action never mutates world state;
every attempt, valid or not, records exactly one event.

This module is part of the engine package and deliberately touches World
internals — the two evolve together. Nothing outside the package may do
the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.simulation.budget import LimitExceeded
from app.simulation.events import Event, EventTypes
from app.simulation.technology import Recipe, invention_for, knowledge_item
from app.simulation.world import (
    BLOCK_RECIPES,
    RESOURCE_OF_OBJECT,
    WATER_RESOURCE,
    Position,
    Terrain,
    World,
)

RESOURCE_SOURCES = {
    resource: object_type for object_type, resource in RESOURCE_OF_OBJECT.items()
}  # resource kind -> object type that yields it
GATHER_YIELD = 1  # units per gather action (scarcity is the point)

DIRECTIONS: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    actor_id: int | None
    action: dict
    event: Event
    data: dict = field(default_factory=dict)

    @property
    def reason(self) -> str | None:
        return self.data.get("reason")


class _Rejected(Exception):
    """Internal control flow: a rule violation carrying a reason."""

    def __init__(self, reason: str, data: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.data = data or {}


HANDLERS = {
    "move": "_move",
    "look": "_look",
    "inspect": "_inspect",
    "pick_up": "_pick_up",
    "drop": "_drop",
    "place": "_place",
    "gather": "_gather",
    "build": "_build",
    "remove": "_remove",
    "say": "_say",
    "tell": "_tell",
    "announce": "_announce",
    "broadcast": "_broadcast",
    "discover": "_discover",
    "craft": "_craft",
    "invent": "_invent",
    "settle": "_settle",
    "join_settlement": "_join_settlement",
    "adopt": "_adopt",
    "deposit": "_deposit",
    "withdraw": "_withdraw",
    "pave": "_pave",
    "claim_zone": "_claim_zone",
    "release_zone": "_release_zone",
    "play": "_play",
    "give": "_give",
    "take": "_take",
    "trade": "_trade",
    "follow": "_follow",
    "unfollow": "_unfollow",
}


def execute_action(world: World, actor_id, action) -> ActionResult:
    """Validate and apply one action proposal."""
    if not isinstance(action, dict):
        return world._record_action(
            ok=False, actor_id=actor_id, action={}, data={"reason": "invalid_action"}
        )

    handler_name = HANDLERS.get(action.get("action"))
    if handler_name is None:
        return world._record_action(
            ok=False,
            actor_id=actor_id,
            action=action,
            data={"reason": "unknown_action"},
        )

    handler = globals()[handler_name]
    # S33: the action budget binds before the run reaches the handler —
    # an entity out of actions is refused here, not deep inside a
    # half-applied rule.
    try:
        world._spend_budget(actor_id, "actions")
    except LimitExceeded as exc:
        return world._record_action(
            ok=False,
            actor_id=actor_id,
            action=action,
            data={"reason": "action_budget_exceeded", "kind": exc.kind, "remaining": exc.remaining},
        )
    try:
        data = handler(world, actor_id, action)
    except _Rejected as exc:
        return world._record_action(
            ok=False,
            actor_id=actor_id,
            action=action,
            data={"reason": exc.reason, **exc.data},
        )
    return world._record_action(ok=True, actor_id=actor_id, action=action, data=data)


def _gather(world: World, actor_id, action: dict) -> dict:
    """Move one unit of a resource from an adjacent source into the
    actor's ledger (S17).

    Sources: the object type that yields the resource (a tree for
    wood), or an adjacent water tile for water. A source that hits
    zero is depleted and leaves the world. Rejections record like any
    other rule violation; nothing is half-applied.
    """
    position = _require_actor(world, actor_id)
    resource = action.get("resource")
    if not isinstance(resource, str) or (
        resource not in RESOURCE_SOURCES and resource != WATER_RESOURCE
    ):
        raise _Rejected("unknown_resource", {"resource": resource})

    if resource == WATER_RESOURCE:
        if not any(
            world.in_bounds(Position(position.x + dx, position.y + dy))
            and world.terrain_at(Position(position.x + dx, position.y + dy)) is Terrain.WATER
            for dx, dy in DIRECTIONS.values()
        ):
            raise _Rejected("no_water_nearby", {"resource": resource})
        world.credit_resource(actor_id, resource, GATHER_YIELD)
        return {"resource": resource, "amount": GATHER_YIELD}

    source_type = RESOURCE_SOURCES[resource]
    # A tool the carrier holds deepens the cut (S29): the axe is the
    # first discovery that pays for itself on the very next action.
    amount = GATHER_YIELD * world.tool_effect(actor_id, "gather")
    for dx, dy in DIRECTIONS.values():
        cell = Position(position.x + dx, position.y + dy)
        if not world.in_bounds(cell):
            continue
        obj = world.object_at(cell)
        if obj is None or obj.type != source_type:
            continue
        quantity = obj.properties.get("quantity", 0)
        if not isinstance(quantity, int) or quantity <= 0:
            continue
        # A claimed source refuses outsiders (S30): the Void's first
        # property rule. Members of the holding settlement gather
        # freely; everyone else is told whose it is.
        claimer = world.zone_claimer(obj.id)
        if claimer is not None and not world.is_settlement_member(actor_id, claimer):
            raise _Rejected(
                "claimed_by",
                {"settlement_id": claimer, "object_id": obj.id},
            )
        obj.properties["quantity"] = quantity - amount
        world.credit_resource(actor_id, resource, amount)
        depleted = False
        if obj.properties["quantity"] <= 0:
            world.remove_object(obj.id)
            depleted = True
        return {
            "resource": resource,
            "amount": amount,
            "source_object_id": obj.id,
            "depleted": depleted,
        }
    raise _Rejected("no_source_nearby", {"resource": resource, "wanted": source_type})


def _build(world: World, actor_id, action: dict) -> dict:
    """Place a block on an adjacent cell, spending its materials (S18).

    The block occupies its cell (a wall is a wall). It joins an
    adjacent structure by adjacency — the guide's "a building is a
    collection of world objects with relationships" — or starts a new
    one owned by the builder, unless an explicit structure id says
    otherwise. Material costs come from the ledger (S17): no wood, no
    block.
    """
    position = _require_actor(world, actor_id)
    block_type = action.get("block")
    if block_type not in BLOCK_RECIPES:
        raise _Rejected("unknown_block", {"block": block_type})

    direction = action.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise _Rejected("invalid_direction", {"direction": direction})
    dx, dy = DIRECTIONS[direction]
    target = Position(position.x + dx, position.y + dy)
    if not world.in_bounds(target):
        raise _Rejected("out_of_bounds", {"to": target.to_dict()})
    if world.terrain_at(target) is not Terrain.FLOOR:
        raise _Rejected("impassable_terrain", {"to": target.to_dict()})
    if target in world._occupancy:
        raise _Rejected("cell_occupied", {"to": target.to_dict()})
    if target in world._entity_cells:
        raise _Rejected("cell_occupied", {"to": target.to_dict(), "entity_id": world._entity_cells[target]})

    recipe = BLOCK_RECIPES[block_type]
    if not all(world.resource_count(actor_id, kind) >= amount for kind, amount in recipe.items()):
        raise _Rejected(
            "insufficient_materials",
            {"block": block_type, "cost": recipe, "carried": world.resources(actor_id)},
        )

    structure_id = action.get("structure")
    if structure_id is not None and world.structure_by_id(structure_id) is None:
        raise _Rejected("unknown_structure", {"structure": structure_id})

    for kind, amount in recipe.items():
        world.spend_resource(actor_id, kind, amount)

    purpose = action.get("purpose")
    if not isinstance(purpose, str):
        purpose = None
    if structure_id is None:
        structure_id = world.structure_for_cell(target)
    if structure_id is None:
        structure_id = world.create_structure(owner=actor_id, purpose=purpose)
    elif purpose is not None:
        # Joining can designate: a builder naming the structure it adds to.
        world.structure_by_id(structure_id).purpose = purpose

    obj = world.place_object(
        block_type,
        target,
        properties={"material": recipe, "placed_by": actor_id, "structure_id": structure_id},
        created_by_agent_id=actor_id,
    )
    world.add_to_structure(structure_id, obj.id)
    # S30: a member raising a structure inside its settlement's extent
    # grows the settlement on the spot.
    world.maybe_adopt(actor_id, structure_id)
    return {
        "block": block_type,
        "object_id": obj.id,
        "structure_id": structure_id,
        "position": target.to_dict(),
    }


def _remove(world: World, actor_id, action: dict) -> dict:
    """Remove a placed block from an adjacent cell (S18).

    The block's material goes back to the actor's ledger, its cell is
    free again, and it leaves its structure — an emptied structure is
    gone.
    """
    position = _require_actor(world, actor_id)
    direction = action.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise _Rejected("invalid_direction", {"direction": direction})
    dx, dy = DIRECTIONS[direction]
    target = Position(position.x + dx, position.y + dy)
    obj = world.object_at(target)
    if obj is None or "structure_id" not in obj.properties:
        raise _Rejected("not_a_block", {"position": target.to_dict()})

    material = obj.properties.get("material") or {}
    world.remove_block(obj.id)
    for kind, amount in material.items():
        if amount > 0:
            world.credit_resource(actor_id, kind, amount)
    return {"block": obj.type, "object_id": obj.id, "refunded": dict(material)}


def _say(world: World, actor_id, action: dict) -> dict:
    """Speak aloud (S21). Anyone can — the participant or an agent.

    The utterance is recorded as a SPEECH event and enters the local
    speech buffer; hearing is proximity-based (World.messages_for).
    """
    _require_actor(world, actor_id)
    message = action.get("message")
    if not isinstance(message, str) or not message.strip():
        raise _Rejected("empty_message", {})
    message = message.strip()
    world.say(actor_id, message)
    return {"message": message}


# ----------------------------------------------------------------------
# Communication networks (S28)
# ----------------------------------------------------------------------


def _spoken_message(action: dict) -> str:
    message = action.get("message")
    if not isinstance(message, str) or not message.strip():
        raise _Rejected("empty_message", {})
    return message.strip()


def _tell(world: World, actor_id, action: dict) -> dict:
    """A named letter to one entity, wherever it stands (S28).

    Distance does not matter — only that the recipient is in the
    world, and is not the sender writing to themselves.
    """
    _require_actor(world, actor_id)
    target_id = action.get("target")
    if not isinstance(target_id, int) or isinstance(target_id, bool):
        raise _Rejected("invalid_target", {"target": target_id})
    if target_id == actor_id:
        raise _Rejected("cannot_target_self", {})
    if world.entity_position(target_id) is None:
        raise _Rejected("unknown_target", {"target": target_id})
    message = _spoken_message(action)
    world.tell(actor_id, target_id, message)
    return {"message": message, "target": target_id}


def _announce(world: World, actor_id, action: dict) -> dict:
    """One message to the actor's whole group (S28).

    ``scope`` is ``team`` (the S25 covenant) or ``population`` (the
    S27 boundary). Announcing to a group you do not belong to is a
    rejection, not silence.
    """
    _require_actor(world, actor_id)
    scope = action.get("scope")
    if scope not in ("team", "population"):
        raise _Rejected("unknown_scope", {"scope": scope})
    if scope == "team" and world.team_of(actor_id) is None:
        raise _Rejected("not_on_a_team", {})
    if scope == "population" and world.population_of(actor_id) is None:
        raise _Rejected("no_population", {})
    message = _spoken_message(action)
    event = world.announce(actor_id, scope, message)
    return {
        "message": message,
        "scope": scope,
        "recipients": event.payload["recipients"],
    }


def _broadcast(world: World, actor_id, action: dict) -> dict:
    """One message to every entity in the world (S28)."""
    _require_actor(world, actor_id)
    message = _spoken_message(action)
    event = world.broadcast(actor_id, message)
    return {"message": message, "recipients": event.payload["recipients"]}


# ----------------------------------------------------------------------
# Technology (S29)
# ----------------------------------------------------------------------


def _discover(world: World, actor_id, action: dict) -> dict:
    """Experiment with what you carry and learn a recipe (S29).

    Discovery needs materials to experiment with: a recipe the world
    knows becomes known to the actor when its inputs are affordable
    from the actor's ledger. The first such undiscovered recipe (by
    name, so runs are reproducible) is learned; nothing else changes.
    """
    _require_actor(world, actor_id)
    candidates = world.discoverable(actor_id)
    if not candidates:
        raise _Rejected("nothing_to_discover", {"carried": world.resources(actor_id)})
    recipe = candidates[0]
    world.grant_knowledge(actor_id, [knowledge_item(recipe)])
    world._add_event(
        EventTypes.INVENTION,
        actor_id=actor_id,
        payload={
            "kind": "discovery",
            "name": recipe.name,
            "inputs": dict(recipe.inputs),
            "produces": recipe.produces,
        },
    )
    return {"discovered": recipe.name, "produces": recipe.produces}


def _craft(world: World, actor_id, action: dict) -> dict:
    """Make a thing from materials, by a recipe you know (S29).

    The recipe must be in the actor's known technology; the inputs are
    spent from the ledger; the thing comes to be carried. A tool is
    usable the moment it exists — the axe pays on the next gather.
    """
    _require_actor(world, actor_id)
    name = action.get("recipe")
    if not isinstance(name, str) or name not in world.known_recipes(actor_id):
        raise _Rejected("unknown_recipe", {"recipe": name, "known": world.known_recipes(actor_id)})
    recipe = world.recipes[name]
    ledger = world.resources(actor_id)
    if not recipe.affordable_by(ledger):
        raise _Rejected(
            "insufficient_materials", {"recipe": name, "cost": recipe.inputs, "carried": ledger}
        )
    for kind, amount in recipe.inputs.items():
        world.spend_resource(actor_id, kind, amount)
    obj = world.carve_object(recipe.produces, actor_id, {"recipe": name, "crafted_by": actor_id})
    world._add_event(
        EventTypes.CRAFT,
        actor_id=actor_id,
        target_id=obj.id,
        payload={
            "recipe": name,
            "object_id": obj.id,
            "object_type": recipe.produces,
            "inputs": dict(recipe.inputs),
        },
    )
    return {
        "recipe": name,
        "object_id": obj.id,
        "object_type": recipe.produces,
        "tool": recipe.produces,
    }


def _invent(world: World, actor_id, action: dict) -> dict:
    """Combine two things you know into one new thing (S29).

    Combination is deterministic — the table is the world's chemistry.
    Both inputs must be knowledge the actor holds; the result is new
    to the actor; and inventing the same thing twice is refused, not
    silently repeated.
    """
    _require_actor(world, actor_id)
    first, second = action.get("a"), action.get("b")
    known = set(world.technology_of(actor_id))
    for item in (first, second):
        if not isinstance(item, str) or item not in known:
            raise _Rejected("unknown_knowledge", {"knowledge": item})
    result = invention_for(first, second)
    if result is None:
        raise _Rejected("no_such_invention", {"a": first, "b": second})
    already = knowledge_item(result)
    if already in world.technology_of(actor_id):
        raise _Rejected("already_invented", {"invention": already})
    if isinstance(result, Recipe):
        world.add_recipe(result)
    else:
        world.add_pattern(result)
    world.grant_knowledge(actor_id, [already])
    world._add_event(
        EventTypes.INVENTION,
        actor_id=actor_id,
        payload={
            "kind": "invention",
            "from": sorted((first, second)),
            "result": already,
            "result_kind": "recipe" if isinstance(result, Recipe) else "pattern",
        },
    )
    return {
        "invented": already,
        "kind": "recipe" if isinstance(result, Recipe) else "pattern",
    }


# ----------------------------------------------------------------------
# Settlements (S30)
# ----------------------------------------------------------------------


def _settlement(world: World, actor_id, action: dict):
    """The settlement named by an action, which the actor must belong to.

    Naming one's own settlement is optional — an agent banking wood
    into its own village's storehouse should not have to say its id.
    """
    _require_actor(world, actor_id)
    settlement_id = action.get("settlement_id")
    if settlement_id is None:
        settlement = world.settlement_of(actor_id)
        if settlement is None:
            raise _Rejected("no_settlement", {})
        return settlement
    if not isinstance(settlement_id, int) or isinstance(settlement_id, bool):
        raise _Rejected("invalid_settlement", {"settlement": settlement_id})
    settlement = world.settlement(settlement_id)
    if settlement is None:
        raise _Rejected("unknown_settlement", {"settlement": settlement_id})
    if not settlement.is_member(actor_id):
        raise _Rejected(
            "not_a_member", {"settlement": settlement.name, "settlement": settlement_id}
        )
    return settlement


def _call(world: World, actor_id, action: dict, method: str, **kwargs):
    """Run a settlement method, turning its rule violations into rejections."""
    settlement = _settlement(world, actor_id, action)
    try:
        return getattr(world, method)(actor_id, settlement.id, **kwargs)
    except ValueError as exc:
        raise _Rejected("refused", {"detail": str(exc), "settlement": settlement.name})


def _settle(world: World, actor_id, action: dict) -> dict:
    """Found a settlement on a standing structure (S30).

    The structure defaults to one beside the actor. A name is the
    settlement's identity — the world's first proper noun spoken by a
    builder, not a scenario author.
    """
    _require_actor(world, actor_id)
    name = action.get("name")
    structure_id = action.get("structure")
    if structure_id is None:
        position = world.entity_position(actor_id)
        for settlement_structure in world.structures():
            if world._is_adjacent_to_structure(actor_id, settlement_structure.id):
                structure_id = settlement_structure.id
                break
    if not isinstance(name, str) or not name.strip():
        raise _Rejected("invalid_name", {"name": name})
    try:
        settlement = world.found_settlement(actor_id, name, structure_id)
    except ValueError as exc:
        raise _Rejected("cannot_settle", {"detail": str(exc)})
    return {
        "settlement_id": settlement.id,
        "name": settlement.name,
        "structure_id": structure_id,
    }


def _join_settlement(world: World, actor_id, action: dict) -> dict:
    """Join a settlement of your own people (S30)."""
    _require_actor(world, actor_id)
    settlement_id = action.get("settlement_id")
    try:
        settlement = world.join_settlement(actor_id, settlement_id)
    except ValueError as exc:
        raise _Rejected("cannot_join", {"detail": str(exc)})
    return {"settlement_id": settlement.id, "name": settlement.name}


def _adopt(world: World, actor_id, action: dict) -> dict:
    """Claim a standing structure for your settlement (S30)."""
    _require_actor(world, actor_id)
    structure_id = action.get("structure")
    return _call(
        world, actor_id, action, "adopt_structure", structure_id=structure_id
    )


def _deposit(world: World, actor_id, action: dict) -> dict:
    """Bank a resource into the settlement's shared storage (S30)."""
    _require_actor(world, actor_id)
    resource = action.get("resource")
    amount = action.get("amount", 1)
    return _call(
        world, actor_id, action, "deposit", resource=resource, amount=amount
    )


def _withdraw(world: World, actor_id, action: dict) -> dict:
    """Draw a resource back out of the shared storage (S30)."""
    _require_actor(world, actor_id)
    resource = action.get("resource")
    amount = action.get("amount", 1)
    return _call(
        world, actor_id, action, "withdraw", resource=resource, amount=amount
    )


def _pave(world: World, actor_id, action: dict) -> dict:
    """Lay road cells (S30): a path you can still walk."""
    _require_actor(world, actor_id)
    cells = action.get("cells")
    if cells is None:
        direction = action.get("direction")
        position = world.entity_position(actor_id)
        if direction in DIRECTIONS:
            dx, dy = DIRECTIONS[direction]
            cells = [{"x": position.x + dx, "y": position.y + dy}]
        else:
            raise _Rejected("invalid_direction", {"direction": direction})
    return _call(world, actor_id, action, "pave", cells=cells)


def _claim_zone(world: World, actor_id, action: dict) -> dict:
    """Claim a resource source for your settlement (S30)."""
    _require_actor(world, actor_id)
    resource = action.get("resource")
    object_id = action.get("target", action.get("object_id"))
    return _call(
        world, actor_id, action, "claim_zone", resource=resource, object_id=object_id
    )


def _release_zone(world: World, actor_id, action: dict) -> dict:
    """Let a claimed source go (S30)."""
    _require_actor(world, actor_id)
    object_id = action.get("target", action.get("object_id"))
    return _call(world, actor_id, action, "release_zone", object_id=object_id)


# ----------------------------------------------------------------------
# Games (S31)
# ----------------------------------------------------------------------


def _play(world: World, actor_id, action: dict) -> dict:
    """Play your turn at a table you sit at (S31).

    The interpreter decides everything — whose turn it is, what is
    legal, who won. A move that is not yours, not legal or not over
    is a rejection, never a state change.
    """
    _require_actor(world, actor_id)
    session_id = action.get("game", action.get("session_id"))
    move_name = action.get("move")
    session = world.session(session_id) if isinstance(session_id, int) else None
    if session is None:
        raise _Rejected("unknown_game", {"game": session_id})
    if not isinstance(move_name, str) or not move_name:
        raise _Rejected("invalid_move", {"move": move_name})
    if session.status == "finished":
        raise _Rejected("game_over", {"game": session_id})
    if session.status != "playing":
        raise _Rejected("not_ready", {"game": session_id})
    if actor_id not in session.players:
        raise _Rejected("not_a_player", {"game": session_id})
    if actor_id != session.current_player:
        raise _Rejected("not_your_turn", {"game": session_id})
    if move_name not in session.rules["moves"]:
        raise _Rejected("unknown_move", {"game": session_id, "move": move_name})
    if move_name not in session.legal_moves(actor_id):
        raise _Rejected("illegal_move", {"game": session_id, "move": move_name})
    outcome = world.play_move(session_id, actor_id, move_name)
    return {
        "game": session_id,
        "move": move_name,
        "state": outcome["state"],
        "points": outcome["points"],
        "winner": outcome["winner"],
        "win_reason": outcome["win_reason"],
    }


# ----------------------------------------------------------------------
# Social interaction (S22)
# ----------------------------------------------------------------------


def _require_adjacent_entity(world: World, actor_id, action: dict):
    """The target entity named by the action, adjacent to the actor."""
    position = _require_actor(world, actor_id)
    target_id = action.get("target")
    if not isinstance(target_id, int) or isinstance(target_id, bool):
        raise _Rejected("invalid_target", {"target": target_id})
    if target_id == actor_id:
        raise _Rejected("cannot_target_self", {})
    target_position = world.entity_position(target_id)
    if target_position is None:
        raise _Rejected("unknown_target", {"target": target_id})
    if not _within_reach(position, target_position):
        raise _Rejected("target_out_of_reach", {"target": target_id})
    return target_id, target_position


def _give(world: World, actor_id, action: dict) -> dict:
    """Hand something you carry to an adjacent entity (S22)."""
    target_id, _ = _require_adjacent_entity(world, actor_id, action)
    if "resource" in action:
        return _transfer_resources(world, actor_id, target_id, action, "give")
    return _transfer_object(world, actor_id, target_id, action, "give")


def _take(world: World, actor_id, action: dict) -> dict:
    """Take something an adjacent entity carries (S22).

    The Void keeps no consent ledger yet — the transfer is recorded
    either way, so the timeline says who took what from whom.
    """
    target_id, _ = _require_adjacent_entity(world, actor_id, action)
    if "resource" in action:
        return _transfer_resources(world, target_id, actor_id, action, "take")
    return _transfer_object(world, target_id, actor_id, action, "take")


def _trade(world: World, actor_id, action: dict) -> dict:
    """Swap with an adjacent entity, atomically (S22).

    Both legs are validated before either moves: if the other side
    cannot deliver what is wanted, nothing changes hands.
    """
    target_id, _ = _require_adjacent_entity(world, actor_id, action)
    offer = action.get("give") or {}
    want = action.get("want") or {}
    if not isinstance(offer, dict) or not isinstance(want, dict):
        raise _Rejected("invalid_trade", {})

    # Validate both legs first — an atomic trade never half-applies.
    if "object_id" in want:
        if world.carried_by(want["object_id"]) != target_id:
            raise _Rejected("trade_target_lacks_object", {"object_id": want["object_id"]})
    elif "resource" in want:
        kind, amount = _resource_leg(want)
        if world.resource_count(target_id, kind) < amount:
            raise _Rejected("trade_target_lacks_resource", {"resource": kind, "amount": amount})
    else:
        raise _Rejected("invalid_trade_want", {})

    if "object_id" in offer:
        if world.carried_by(offer["object_id"]) != actor_id:
            raise _Rejected("trade_self_lacks_object", {"object_id": offer["object_id"]})
    elif "resource" in offer:
        kind, amount = _resource_leg(offer)
        if world.resource_count(actor_id, kind) < amount:
            raise _Rejected("trade_self_lacks_resource", {"resource": kind, "amount": amount})
    else:
        raise _Rejected("invalid_trade_give", {})

    # Both legs validated — apply.
    if "object_id" in offer:
        _apply_object(world, offer["object_id"], actor_id, target_id, "trade")
    else:
        kind, amount = _resource_leg(offer)
        world.spend_resource(actor_id, kind, amount)
        world.credit_resource(target_id, kind, amount)
    if "object_id" in want:
        _apply_object(world, want["object_id"], target_id, actor_id, "trade")
    else:
        kind, amount = _resource_leg(want)
        world.spend_resource(target_id, kind, amount)
        world.credit_resource(actor_id, kind, amount)
    return {"traded_with": target_id, "gave": offer, "received": want}


def _transfer_object(world: World, from_id: int, to_id: int, action: dict, kind: str) -> dict:
    object_id = action.get("object_id")
    if world.carried_by(object_id) != from_id:
        raise _Rejected("not_carrying", {"object_id": object_id})
    _apply_object(world, object_id, from_id, to_id, kind)
    return {"object_id": object_id, "from": from_id, "to": to_id}


def _apply_object(world: World, object_id: int, from_id: int, to_id: int, kind: str) -> None:
    world.transfer_object(object_id, to_id)
    obj = world.get_object(object_id)
    world._add_event(
        EventTypes.TRANSFER,
        actor_id=from_id,
        target_id=to_id,
        payload={
            "kind": kind,
            "what": "object",
            "object_id": object_id,
            "type": obj.type if obj else None,
        },
    )


def _transfer_resources(world: World, from_id: int, to_id: int, action: dict, kind: str) -> dict:
    resource_kind, amount = _resource_leg(action)
    if world.resource_count(from_id, resource_kind) < amount:
        raise _Rejected(
            "insufficient_resources",
            {"resource": resource_kind, "amount": amount,
             "carried": world.resources(from_id)},
        )
    world.spend_resource(from_id, resource_kind, amount)
    world.credit_resource(to_id, resource_kind, amount)
    world._add_event(
        EventTypes.TRANSFER,
        actor_id=from_id,
        target_id=to_id,
        payload={"kind": kind, "what": "resource",
                 "resource": resource_kind, "amount": amount},
    )
    return {"resource": resource_kind, "amount": amount, "from": from_id, "to": to_id}


def _resource_leg(leg: dict) -> tuple[str, int]:
    resource_kind = leg.get("resource")
    amount = leg.get("amount", 1)
    if not isinstance(resource_kind, str):
        raise _Rejected("invalid_resource", {"resource": resource_kind})
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        raise _Rejected("invalid_amount", {"amount": amount})
    return resource_kind, amount


def _follow(world: World, actor_id, action: dict) -> dict:
    """Start walking with an adjacent entity (S22)."""
    target_id, _ = _require_adjacent_entity(world, actor_id, action)
    world.set_follow(actor_id, target_id)
    world._add_event(
        EventTypes.FOLLOW,
        actor_id=actor_id,
        target_id=target_id,
        payload={"kind": "started"},
    )
    return {"following": target_id}


def _unfollow(world: World, actor_id, action: dict) -> dict:
    """Stop following."""
    _require_actor(world, actor_id)
    if not world.clear_follow(actor_id):
        raise _Rejected("not_following", {})
    world._add_event(
        EventTypes.FOLLOW,
        actor_id=actor_id,
        payload={"kind": "stopped"},
    )
    return {"following": None}


# ----------------------------------------------------------------------
# Shared validation
# ----------------------------------------------------------------------


def _require_actor(world: World, actor_id):
    if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id not in world._entities:
        raise _Rejected("unknown_actor", {"actor_id": actor_id})
    return world._entities[actor_id]


def _carried(world: World, actor_id: int, object_id):
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.id not in world._inventory.get(actor_id, []):
        raise _Rejected("not_carrying", {"object_id": object_id})
    return obj


def _within_reach(actor_position, object_position) -> bool:
    if object_position is None:
        return False
    return abs(actor_position.x - object_position.x) + abs(actor_position.y - object_position.y) <= 1


# ----------------------------------------------------------------------
# Handlers — return data on success, raise _Rejected on rule violations
# ----------------------------------------------------------------------


def _move(world: World, actor_id, action: dict) -> dict:
    from app.simulation.world import Position, Terrain

    position = _require_actor(world, actor_id)
    direction = action.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise _Rejected("invalid_direction", {"direction": direction})

    dx, dy = DIRECTIONS[direction]
    target = Position(position.x + dx, position.y + dy)
    if not world.in_bounds(target):
        raise _Rejected("out_of_bounds", {"to": target.to_dict()})
    terrain = world.terrain_at(target)
    if terrain is Terrain.WALL:
        raise _Rejected("wall", {"to": target.to_dict()})
    if terrain is Terrain.WATER:
        raise _Rejected("water", {"to": target.to_dict()})
    if target in world._occupancy:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "object_id": world._occupancy[target]}
        )
    if target in world._entity_cells:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "entity_id": world._entity_cells[target]}
        )

    del world._entity_cells[position]
    world._entities[actor_id] = target
    world._entity_cells[target] = actor_id
    return {"from": position.to_dict(), "to": target.to_dict()}


def _look(world: World, actor_id, action: dict) -> dict:
    from app.simulation.world import Position

    position = _require_actor(world, actor_id)
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
            entity = world._entity_cells.get(cell_pos)
            if entity is not None:
                cell["entity"] = entity
        cells.append(cell)
    return {"position": position.to_dict(), "cells": cells}


def _inspect(world: World, actor_id, action: dict) -> dict:
    position = _require_actor(world, actor_id)
    object_id = action.get("object_id")
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.position is None:
        # Carried: only the carrier can inspect it up close.
        if obj.id not in world._inventory.get(actor_id, []):
            raise _Rejected("carried_elsewhere", {"object_id": obj.id})
    elif not _within_reach(position, obj.position):
        raise _Rejected("out_of_reach", {"object_position": obj.position.to_dict()})
    return {"object": obj.to_dict()}


def _pick_up(world: World, actor_id, action: dict) -> dict:
    position = _require_actor(world, actor_id)
    object_id = action.get("object_id")
    obj = world._objects.get(object_id) if isinstance(object_id, int) else None
    if obj is None:
        raise _Rejected("unknown_object", {"object_id": object_id})
    if obj.position is None:
        raise _Rejected("carried_elsewhere", {"object_id": obj.id})
    if obj.properties.get("heavy"):
        raise _Rejected("too_heavy", {"object_id": obj.id})
    if not _within_reach(position, obj.position):
        raise _Rejected("out_of_reach", {"object_position": obj.position.to_dict()})

    del world._occupancy[obj.position]
    obj.position = None
    world._inventory.setdefault(actor_id, []).append(obj.id)
    return {"object_id": obj.id, "type": obj.type, "from": None}


def _drop(world: World, actor_id, action: dict) -> dict:
    return _release(world, actor_id, action, allow_direction=False)


def _place(world: World, actor_id, action: dict) -> dict:
    return _release(world, actor_id, action, allow_direction=True)


def _release(world: World, actor_id, action: dict, *, allow_direction: bool) -> dict:
    from app.simulation.world import Position, Terrain

    verb = "place" if allow_direction else "drop"
    position = _require_actor(world, actor_id)
    obj = _carried(world, actor_id, action.get("object_id"))

    if allow_direction:
        direction = action.get("direction")
        if not isinstance(direction, str) or direction not in DIRECTIONS:
            raise _Rejected("invalid_direction", {"direction": direction})
        dx, dy = DIRECTIONS[direction]
        target = Position(position.x + dx, position.y + dy)
    else:
        target = position

    if not world.in_bounds(target):
        raise _Rejected("out_of_bounds", {"to": target.to_dict()})
    if world.terrain_at(target) is not Terrain.FLOOR:
        raise _Rejected("impassable_terrain", {"to": target.to_dict()})
    if target in world._occupancy:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "object_id": world._occupancy[target]}
        )
    if allow_direction and target in world._entity_cells:
        raise _Rejected(
            "cell_occupied", {"to": target.to_dict(), "entity_id": world._entity_cells[target]}
        )

    world._inventory[actor_id].remove(obj.id)
    if not world._inventory[actor_id]:
        del world._inventory[actor_id]
    obj.position = target
    world._occupancy[target] = obj.id
    return {"object_id": obj.id, "type": obj.type, "to": target.to_dict(), "verb": verb}
