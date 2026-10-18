"""S42 — Language evolution.

Three checks, straight from the roadmap: a shared vocabulary can emerge,
messages stay parseable, and every change is tracked.
"""

import random

import pytest

from app.experiments.language import run_language_experiment
from app.simulation.events import EventTypes
from app.simulation.geometry import Position
from app.simulation.language import (
    CONCEPTS,
    Lexicon,
    concepts_in,
    mean_agreement,
)
from app.simulation.world import World


def make_world(*entity_ids: int, seed: str = "language") -> World:
    world = World(seed=seed, width=8, height=8)
    for index, entity_id in enumerate(entity_ids or (1, 2)):
        world.add_entity(entity_id, Position(1 + index, 1))
    return world


# --- the lexicon itself -------------------------------------------------


def test_invent_is_deterministic_and_tracked():
    first = Lexicon()
    second = Lexicon()
    symbol_a, invented_a = first.invent("water", random.Random("seed"), tick=3, actor=1)
    symbol_b, invented_b = second.invent("water", random.Random("seed"), tick=3, actor=1)

    assert invented_a and invented_b
    assert symbol_a == symbol_b
    assert first.symbol_for("water") == symbol_a
    assert symbol_a not in CONCEPTS
    assert first.history == [
        {"tick": 3, "kind": "invented", "concept": "water", "symbol": symbol_a, "actor": 1}
    ]


def test_invent_does_not_rename():
    lexicon = Lexicon()
    symbol, _ = lexicon.invent("tree", random.Random("a"))
    same, invented = lexicon.invent("tree", random.Random("b"))
    assert same == symbol and invented is False
    assert len(lexicon.history) == 1


def test_encode_decode_round_trip_keeps_messages_parseable():
    lexicon = Lexicon()
    rng = random.Random("round-trip")
    text = "water and stone by the tree, rain on the path!"
    encoded, innovations = lexicon.encode(text, rng=rng, tick=1, actor=1)

    assert encoded != text
    assert {item["concept"] for item in innovations} == {
        "water", "stone", "tree", "rain", "path",
    }
    assert lexicon.decode(encoded) == text


def test_unknown_words_pass_through_unencoded():
    lexicon = Lexicon()
    encoded, innovations = lexicon.encode("a dragon guards the door")
    assert encoded == "a dragon guards the door"
    assert innovations == []
    # `door` is a concept, but without an RNG an unknown name stays plain.
    assert lexicon.symbol_for("door") is None


def test_pure_encode_never_invents():
    lexicon = Lexicon()
    lexicon.entries["water"] = "kama"
    encoded, innovations = lexicon.encode("water is life")
    assert encoded == "kama is life"
    assert innovations == []


def test_adopt_records_new_replaced_and_noop():
    lexicon = Lexicon()
    assert lexicon.adopt("water", "kama", tick=1, actor=2, source=1) is True
    assert lexicon.history[-1]["kind"] == "adopted"
    assert lexicon.history[-1]["previous"] is None

    assert lexicon.adopt("water", "tomi", tick=2, actor=2, source=3) is True
    assert lexicon.history[-1]["kind"] == "replaced"
    assert lexicon.history[-1]["previous"] == "kama"
    assert lexicon.history[-1]["symbol"] == "tomi"

    assert lexicon.adopt("water", "tomi", tick=3, actor=2) is False
    assert len(lexicon.history) == 2


def test_adopt_never_shadows_a_plain_concept():
    lexicon = Lexicon()
    assert lexicon.adopt("stone", "water") is False
    assert lexicon.entries == {}


def test_agreement_counts_symbols_not_just_concepts():
    left = Lexicon(entries={"water": "kama", "stone": "tomi"})
    right = Lexicon(entries={"water": "kama", "stone": "ravi"})
    third = Lexicon(entries={"water": "kama", "stone": "tomi"})

    assert left.agreement(third) == 1.0
    assert left.agreement(right) == pytest.approx(1 / 3)
    assert left.shared_with(right) == ["water"]
    assert mean_agreement([left, third]) == 1.0
    assert mean_agreement([]) == 1.0


# --- the world ----------------------------------------------------------


def test_speak_invents_names_and_emits_events():
    world = make_world(1, 2)
    event = world.speak(1, "water by the tree")

    symbols = event.payload["symbols"]
    assert event.type == EventTypes.SPEECH
    assert event.payload["text"] == "water by the tree"
    assert set(symbols) == {"water", "tree"}
    assert event.payload["message"] != "water by the tree"
    assert world.lexicon(1).decode(event.payload["message"]) == "water by the tree"

    invented = [e for e in world.events if e.type == EventTypes.WORD_INVENTED]
    assert {e.payload["concept"] for e in invented} == {"water", "tree"}


def test_learning_makes_the_utterance_understood_and_tracked():
    world = make_world(1, 2)
    world.speak(1, "water and stone")

    heard = world.messages_for(2)
    assert heard and "understanding" not in heard[0]  # no lexicon yet

    changes = world.learn(2, 1)
    assert {change["concept"] for change in changes} == {"water", "stone"}
    assert world.lexicon(2).entries == world.lexicon(1).entries

    heard = world.messages_for(2)
    assert heard[0]["understanding"] == "water and stone"
    adopted = [e for e in world.events if e.type == EventTypes.WORD_ADOPTED]
    assert len(adopted) == 2
    assert world.language_summary()["changes"] >= 2


def test_learning_nothing_heard_is_a_noop():
    world = make_world(1, 2)
    assert world.learn(2, 1) == []
    assert world.lexicon(2).entries == {}


def test_learn_rejects_unknown_entities():
    world = make_world(1)
    with pytest.raises(ValueError):
        world.learn(99, 1)
    with pytest.raises(ValueError):
        world.learn(1, 99)


def test_speak_requires_a_speaker():
    world = make_world(1)
    with pytest.raises(ValueError):
        world.speak(99, "water")


def test_language_changes_are_summarized():
    world = make_world(1, 2, 3)
    world.speak(1, "water stone")
    world.learn(2, 1)
    world.learn(3, 1)

    summary = world.language_summary()
    assert summary["agreement"] == 1.0
    assert summary["agents"] and len(summary["agents"]) == 3
    assert {item["concept"] for item in summary["shared_words"]} == {"water", "stone"}
    assert summary["changes"] >= 6


def test_lexicons_and_learnable_speeches_survive_serialization():
    world = make_world(1, 2)
    world.speak(1, "water")
    world.learn(2, 1)
    restored = World.from_dict(world.to_dict())

    assert restored.lexicon(1).entries == world.lexicon(1).entries
    assert restored.lexicon(2).entries == world.lexicon(2).entries
    assert restored.lexicon(1).history == world.lexicon(1).history
    # A restored world can still teach: the learnable symbols ride in the
    # speech buffer, not only in the event log (which snapshots drop).
    restored.add_entity(3, Position(3, 3))
    changes = restored.learn(3, 1)
    assert {change["concept"] for change in changes} == {"water"}


def test_speak_action_encodes_and_say_stays_plain():
    world = make_world(1)
    plain = world.execute_action(1, {"action": "say", "message": "water"})
    assert plain.ok and plain.data["message"] == "water"

    spoken = world.execute_action(1, {"action": "speak", "message": "water"})
    assert spoken.ok
    assert spoken.data["text"] == "water"
    assert spoken.data["message"] != "water"
    assert spoken.data["symbols"] == {"water": world.lexicon(1).symbol_for("water")}


def test_concepts_in():
    assert concepts_in("Water, water and STONE; a dragon") == ["stone", "water"]


# --- the study ----------------------------------------------------------


def test_shared_vocabulary_emerges():
    result = run_language_experiment(agents=5, rounds=12, seed="emerge")

    assert result["agreement_before"] < 0.5  # independent invention diverges
    assert result["agreement_after"] == 1.0
    assert result["converged"] is True
    assert result["agreement_by_round"][-1] == 1.0
    # Convergence means one word per concept, agreed by everyone.
    assert result["vocabulary_after"] == len(result["concepts"])
    assert len(result["shared_words"]) == len(result["concepts"])
    assert result["changes"] > 0


def test_study_is_deterministic_per_seed():
    first = run_language_experiment(seed="repeat")
    second = run_language_experiment(seed="repeat")
    assert first["agreement_by_round"] == second["agreement_by_round"]
    assert first["lexicons"] == second["lexicons"]


def test_study_rejects_bad_input():
    with pytest.raises(ValueError):
        run_language_experiment(agents=1)
    with pytest.raises(ValueError):
        run_language_experiment(rounds=-1)
    with pytest.raises(ValueError):
        run_language_experiment(concepts=("dragon",))
