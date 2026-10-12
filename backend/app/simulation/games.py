"""Games: rules as data, sessions, scoring (S31).

A game is a dictionary — a name, seats, an initial state, named moves
with preconditions and effects, and a win condition. The interpreter
below is the *only* thing that ever runs a game: there is no code in
a rule, so there is nothing to execute but the data. Anything the
interpreter does not know (an unknown key, an undeclared state name,
a move nobody can legally open with) is a rejected proposal, not a
runtime surprise. That closed vocabulary is the whole point of the
sprint's verification: agent-created rules are playable *because*
they can only say what the engine already understands.

The vocabulary, deliberately small:

- state: named counters and flags (ints, strings, booleans).
- requires: ``{"track": "<10"}`` (comparisons on ints) or plain
  equality ``{"flag": "lit"}`` — all keys must be declared in setup.
- effects: ``add`` (counters move), ``set`` (flags flip), ``award``
  (the mover scores points), ``again`` (the mover goes again).
- win: ``first_to`` (the mover whose move reaches a mark wins) or
  ``most_points_after_rounds`` (the table plays N full rounds, then
  the most points win; ties go to the earlier seat).

Turns go round the table in join order. There is no hidden
information and no chance — the sprint's out-list says so plainly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COMPARATORS = ("<=", ">=", "==", "!=", "<", ">")
EFFECT_KEYS = ("add", "set", "award", "again")
MOVE_KEYS = ("requires", "effect", "description")
WIN_KEYS = ("first_to", "most_points_after_rounds")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_scalar(value) -> bool:
    return _is_int(value) or isinstance(value, (str, bool))


def _parse_comparator(text: str) -> tuple[str, int] | None:
    """Split "<10" into ("<", 10); None when it is not a comparison."""
    if not isinstance(text, str):
        return None
    for operator in COMPARATORS:
        if text.startswith(operator):
            try:
                return operator, int(text[len(operator):])
            except ValueError:
                return None
    return None


def _holds(state: dict, requires: dict) -> bool:
    """Whether every precondition holds against the state.

    A key the state does not declare fails (rather than raising): the
    validator refuses such a rule, but ``legal_moves`` is called at the
    table and must never blow up over an undeclared name.
    """
    for key, want in requires.items():
        if key not in state:
            return False
        have = state[key]
        parsed = _parse_comparator(want) if isinstance(want, str) else None
        if parsed is not None:
            operator, number = parsed
            if not _is_int(have):
                return False
            if operator == "<" and not have < number:
                return False
            if operator == "<=" and not have <= number:
                return False
            if operator == "==" and not have == number:
                return False
            if operator == "!=" and not have != number:
                return False
            if operator == ">=" and not have >= number:
                return False
            if operator == ">" and not have > number:
                return False
        elif have != want:
            return False
    return True


def validate_rules(rules: dict) -> list[str]:
    """Check a proposed game; the empty list means it is playable."""
    errors: list[str] = []
    if not isinstance(rules, dict):
        return ["rules must be a mapping"]
    name = rules.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("a game needs a non-empty name")
    players = rules.get("players")
    if not _is_int(players) or players < 2:
        errors.append("players must be an integer of at least 2")
    setup = rules.get("setup")
    if not isinstance(setup, dict):
        errors.append("setup must be a mapping of state names to values")
        setup = {}
    else:
        for key, value in setup.items():
            if not isinstance(key, str) or not key:
                errors.append(f"state names must be non-empty strings, got {key!r}")
            elif not _is_scalar(value):
                errors.append(f"state {key!r} must be an int, string or boolean")
    moves = rules.get("moves")
    if not isinstance(moves, dict) or not moves:
        errors.append("moves must be a non-empty mapping of move names")
        moves = {}
    else:
        for move_name, move in moves.items():
            if not isinstance(move_name, str) or not move_name:
                errors.append(f"move names must be non-empty strings, got {move_name!r}")
                continue
            if not isinstance(move, dict):
                errors.append(f"move {move_name!r} must be a mapping")
                continue
            for key in move:
                if key not in MOVE_KEYS:
                    errors.append(f"move {move_name!r} has an unknown key {key!r}")
            requires = move.get("requires", {})
            if not isinstance(requires, dict):
                errors.append(f"move {move_name!r} requires must be a mapping")
            else:
                for key, want in requires.items():
                    if key not in setup:
                        errors.append(
                            f"move {move_name!r} requires undeclared state {key!r}"
                        )
                    elif isinstance(want, str) and _parse_comparator(want) is None and want != setup.get(key):
                        # A string precondition is either a comparison
                        # or an exact match; anything else names nothing.
                        if not isinstance(setup.get(key), str):
                            errors.append(
                                f"move {move_name!r} compares {key!r} against {want!r}"
                            )
                    elif not _is_scalar(want) and _parse_comparator(want) is None:
                        errors.append(
                            f"move {move_name!r} precondition on {key!r} is not a value"
                        )
            effect = move.get("effect", {})
            if not isinstance(effect, dict):
                errors.append(f"move {move_name!r} effect must be a mapping")
            else:
                for key in effect:
                    if key not in EFFECT_KEYS:
                        errors.append(f"move {move_name!r} has an unknown effect {key!r}")
                add = effect.get("add", {})
                if not isinstance(add, dict) or any(
                    key not in setup or not _is_int(setup[key]) or not _is_int(amount)
                    for key, amount in add.items()
                ):
                    errors.append(
                        f"move {move_name!r} add must map declared counters to integers"
                    )
                set_ = effect.get("set", {})
                if not isinstance(set_, dict) or any(
                    key not in setup or not _is_scalar(value)
                    for key, value in set_.items()
                ):
                    errors.append(
                        f"move {move_name!r} set must map declared state to values"
                    )
                award = effect.get("award", 0)
                if not _is_int(award) or award < 0:
                    errors.append(f"move {move_name!r} award must be a non-negative integer")
                again = effect.get("again", False)
                if not isinstance(again, bool):
                    errors.append(f"move {move_name!r} again must be true or false")
    win = rules.get("win")
    if not isinstance(win, dict) or set(win) - set(WIN_KEYS) or len(win) != 1:
        errors.append(f"win must be exactly one of {list(WIN_KEYS)}")
    else:
        if "first_to" in win:
            mark = win["first_to"]
            if not isinstance(mark, dict) or len(mark) != 1:
                errors.append("first_to must name one state and its mark")
            else:
                (key, value), = mark.items()
                if key not in setup:
                    errors.append(f"first_to names undeclared state {key!r}")
                elif not _is_scalar(value):
                    errors.append("first_to marks must be plain values")
        else:
            rounds = win["most_points_after_rounds"]
            if not _is_int(rounds) or rounds < 1:
                errors.append("most_points_after_rounds must be an integer of at least 1")
    # A game nobody can start is not a game.
    if (
        isinstance(moves, dict)
        and moves
        and isinstance(setup, dict)
        and not any(
            isinstance(move, dict) and _holds(setup, move.get("requires", {}))
            for move in moves.values()
        )
    ):
        errors.append("no move is legal in the setup state: the game cannot open")
    return errors


@dataclass
class GameSession:
    """One table playing one game: players, state, score, turn, winner."""

    id: int
    name: str
    rules: dict
    players: list[int] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    points: dict[int, int] = field(default_factory=dict)
    turn_index: int = 0
    rounds_completed: int = 0
    status: str = "open"  # open -> playing -> finished
    winner: int | None = None
    win_reason: str | None = None
    history: list[dict] = field(default_factory=list)

    @property
    def seats(self) -> int:
        return self.rules["players"]

    @property
    def current_player(self) -> int | None:
        if not self.players or self.status != "playing":
            return None
        return self.players[self.turn_index % len(self.players)]

    def legal_moves(self, entity_id: int) -> list[str]:
        """The moves this entity may play now (empty when it is not
        their turn, the table is not full, or the game is over)."""
        if self.status != "playing" or entity_id != self.current_player:
            return []
        return [
            name
            for name, move in self.rules["moves"].items()
            if _holds(self.state, move.get("requires", {}))
        ]

    def play(self, entity_id: int, move_name: str, tick: int) -> dict:
        """Play a move: validate, apply, score, judge, advance."""
        if self.status == "finished":
            raise ValueError(f"game {self.id} is already over")
        if self.status != "playing":
            raise ValueError(f"game {self.id} is not ready: the table is not full")
        if entity_id != self.current_player:
            raise ValueError(f"it is not {entity_id}'s turn in game {self.id}")
        if move_name not in self.rules["moves"]:
            raise ValueError(f"game {self.id} has no move {move_name!r}")
        move = self.rules["moves"][move_name]
        if not _holds(self.state, move.get("requires", {})):
            raise ValueError(f"move {move_name!r} is not legal in game {self.id}")
        effect = move.get("effect", {})
        for key, amount in effect.get("add", {}).items():
            self.state[key] += amount
        for key, value in effect.get("set", {}).items():
            self.state[key] = value
        self.points[entity_id] = self.points.get(entity_id, 0) + effect.get("award", 0)
        self.history.append(
            {
                "tick": tick,
                "player": entity_id,
                "move": move_name,
                "state": dict(self.state),
                "points": dict(self.points),
            }
        )
        outcome = self._judge(entity_id)
        if outcome is None and not effect.get("again", False):
            self.turn_index += 1
            if self.turn_index >= len(self.players):
                self.turn_index = 0
                self.rounds_completed += 1
                outcome = self._judge_rounds()
        if outcome is not None:
            self.status = "finished"
            self.winner, self.win_reason = outcome
        return {
            "move": move_name,
            "state": dict(self.state),
            "points": dict(self.points),
            "winner": self.winner,
            "win_reason": self.win_reason,
        }

    def _judge(self, mover: int) -> tuple[int, str] | None:
        win = self.rules["win"]
        if "first_to" in win:
            (key, mark), = win["first_to"].items()
            value = self.state[key]
            reached = value >= mark if _is_int(value) and _is_int(mark) else value == mark
            if reached:
                return mover, f"first to {key} {mark}"
        return None

    def _judge_rounds(self) -> tuple[int, str] | None:
        win = self.rules["win"]
        if "most_points_after_rounds" in win and self.rounds_completed >= win["most_points_after_rounds"]:
            best = max(
                self.players,
                key=lambda player: (self.points.get(player, 0), -self.players.index(player)),
            )
            return best, f"most points after {win['most_points_after_rounds']} rounds"
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rules": self.rules,
            "players": list(self.players),
            "state": dict(self.state),
            "points": dict(self.points),
            "current_player": self.current_player,
            "rounds_completed": self.rounds_completed,
            "status": self.status,
            "winner": self.winner,
            "win_reason": self.win_reason,
            "history": [dict(entry) for entry in self.history],
        }


# The calibration game: a footrace down a track of ten. Stride while
# the mark is ahead; the first to the mark wins.
LONG_ROAD = {
    "name": "The Long Road",
    "players": 2,
    "setup": {"track": 0},
    "description": "Stride down the track; first to ten wins.",
    "moves": {
        "stride": {
            "description": "one step down the track",
            "requires": {"track": "<10"},
            "effect": {"add": {"track": 1}},
        },
    },
    "win": {"first_to": {"track": 10}},
}


class PlayerPolicy:
    """A scripted player: play the first legal move at your tables.

    An instrument, not a mind — it knows nothing about the game but
    what the observation shows (your turn, your legal moves), which is
    exactly what makes it a fair opponent for an invented game.
    """

    def decide(self, observation: dict) -> dict:
        for game in observation.get("games", []):
            if game["your_turn"] and game["legal_moves"]:
                return {
                    "action": {
                        "action": "play",
                        "game": game["session_id"],
                        "move": game["legal_moves"][0],
                    }
                }
        return {"action": {"action": "look"}}
