"""S46 — observer vs participant: one seed, two histories.

The roadmap's question — does a world develop differently when a human
enters it? — is verified here at three levels: the participant plan does
exactly what it claims on a controlled world; the paired study produces
deterministic, complete measures with the participant as the only
difference; and the whole thing is discoverable, runnable, stored and
exportable through the experiment API.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.experiments import router as experiments_router
from app.api.worlds import router as worlds_router
from app.experiments.multi_world import resolve_template
from app.experiments.observer import (
    DIMENSIONS,
    MEASURES,
    ParticipantPlan,
    apply_participant_plan,
    compare_runs,
    measure_world,
    run_study,
    run_world,
)
from app.host import PARTICIPANT_ENTITY_ID, WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, World


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'observer.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    application = FastAPI()
    application.include_router(worlds_router, prefix="/api")
    application.include_router(experiments_router, prefix="/api")
    application.state.session_factory = factory
    application.state.worlds = WorldRegistry(factory)
    with TestClient(application) as test_client:
        yield test_client
    engine.dispose()


# ----------------------------------------------------------------------
# The participant plan
# ----------------------------------------------------------------------


def test_participant_plan_round_trips():
    plan = ParticipantPlan(
        population_id=2,
        facts=("fire is hot",),
        task="survive the winter",
        objects=(("monument", 1), ("tree", 3)),
        message="water stone",
        teach=False,
    )
    restored = ParticipantPlan.from_dict(plan.to_dict())
    assert restored == plan


def test_participant_plan_defaults_are_deterministic():
    a, b = ParticipantPlan(), ParticipantPlan()
    assert a.to_dict() == b.to_dict()


def test_participant_plan_accepts_pair_or_dict_objects():
    from_pairs = ParticipantPlan.from_dict({"objects": [["tree", 4]]})
    from_dicts = ParticipantPlan.from_dict(
        {"objects": [{"type": "tree", "quantity": 4}]}
    )
    assert from_pairs.objects == from_dicts.objects == (("tree", 4),)


# ----------------------------------------------------------------------
# The participant's first tick, on a controlled world
# ----------------------------------------------------------------------


@pytest.fixture()
def inhabited_world():
    world = World("plan", 14, 14)
    engine = Engine(world, population_id=1)
    agent = Agent(agent_id=1, policy=WanderPolicy())
    engine.spawn_agent(agent, Position(6, 6))
    world.add_entity(PARTICIPANT_ENTITY_ID, Position(6, 7))  # adjacent, south
    world.set_population(PARTICIPANT_ENTITY_ID, 1)
    return world, engine


def test_the_plan_teaches_tasks_and_places_objects(inhabited_world):
    world, engine = inhabited_world
    plan = ParticipantPlan(
        population_id=1,
        facts=("water is life", "recipe:door"),
        task="build a shelter before winter",
        objects=(("monument", 2),),
        message="water stone fire",
        teach=True,
    )

    applied = apply_participant_plan(world, engine.agents, plan)

    assert applied["population_id"] == 1
    assert applied["facts"] == ["water is life", "recipe:door"]
    assert "water is life" in engine.agents[0].knowledge
    assert "recipe:door" in engine.agents[0].knowledge
    assert applied["task"] == plan.task
    assert engine.agents[0].goal == plan.task

    assert len(applied["objects"]) == 1
    placed = world.object_at(Position(applied["objects"][0]["position"]["x"],
                                      applied["objects"][0]["position"]["y"]))
    assert placed is not None and placed.type == "monument"
    here = world.entity_position(PARTICIPANT_ENTITY_ID)
    distance = abs(placed.position.x - here.x) + abs(placed.position.y - here.y)
    assert distance <= 1  # the human drops things at their feet

    assert applied["speech"]["text"] == "water stone fire"
    taught = [entry for entry in applied["listeners"] if entry["agent_id"] == 1]
    assert taught and taught[0]["learned"] > 0  # the listener heard the words

    assert applied["actions"] == 6  # 2 facts + task + object + speech + join


def test_the_plan_leaves_an_observer_world_untouched():
    template = resolve_template("void")
    run = run_world(template, "still", ticks=4)
    assert run["role"] == "observer"
    assert run["participant"] is None
    assert run["measures"]["participant_actions"] == 0
    assert run["measures"]["entities"] == template.agents


# ----------------------------------------------------------------------
# Measures and the paired comparison
# ----------------------------------------------------------------------


def test_measure_world_covers_every_measure():
    template = resolve_template("void")
    world = World.generate("measured", template.width, template.height)
    engine = Engine(world, population_id=1)
    from app.experiments.multi_world import _spawn_spots

    spots = _spawn_spots(world, template.agents)
    for index, spot in enumerate(spots):
        engine.spawn_agent(
            Agent(agent_id=index + 1, policy=WanderPolicy(), observation_radius=3),
            spot,
        )
    measures = measure_world(world, engine.agents)
    assert set(measures) == set(MEASURES)
    assert all(isinstance(value, (int, float)) for value in measures.values())
    # agreement is a mean pairwise Jaccard — the one fractional measure
    assert isinstance(measures["agreement"], float)


def test_observer_runs_are_deterministic():
    template = resolve_template("void")
    first = run_world(template, "same", ticks=6)
    second = run_world(template, "same", ticks=6)
    assert first["measures"] == second["measures"]


def test_the_participant_is_the_only_difference():
    template = resolve_template("void")
    observer = run_world(template, "pair", ticks=6)
    participant = run_world(template, "pair", ticks=6, participant=True)

    comparison = compare_runs(observer, participant)
    assert set(comparison["dimensions"]) == set(DIMENSIONS)

    deltas = comparison["dimensions"]
    assert deltas["development"]["delta"]["entities"] >= 1  # the human is in there
    assert deltas["behavior"]["delta"]["participant_actions"] > 0
    assert deltas["culture"]["delta"]["knowledge_facts"] > 0  # they taught
    assert deltas["communication"]["delta"]["speech"] > 0  # they spoke
    assert comparison["differing"]  # the worlds are not identical


def test_run_study_stores_and_exports(session_factory, tmp_path):
    export_path = tmp_path / "study.json"
    study = run_study(
        session_factory=session_factory,
        template="void",
        seed="stored",
        ticks=6,
        export_path=str(export_path),
    )

    assert study["experiment_id"] > 0
    assert study["comparison"]["differing"]
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["scenario"] == "observer_vs_participant"
    assert exported["comparison"]["differing"] == study["comparison"]["differing"]

    with session_factory() as session:
        row = session.get(ExperimentModel, study["experiment_id"])
        assert row.scenario == "observer_vs_participant"
        assert row.status == "completed"
        assert row.result["participant"]["measures"]["knowledge_facts"] > 0
        assert row.result["observer"]["measures"]["knowledge_facts"] >= 0


def test_rejections_are_counted_for_both_sides(session_factory):
    study = run_study(session_factory=session_factory, template="void", seed="rejects", ticks=8)
    for side in ("observer", "participant"):
        assert "rejections" in study[side]["measures"]
        assert study[side]["measures"]["rejections"] >= 0


# ----------------------------------------------------------------------
# Through the experiment API
# ----------------------------------------------------------------------


def test_the_catalog_lists_the_new_scenario(client):
    body = client.get("/api/scenarios").json()
    names = {scenario["name"] for scenario in body["scenarios"]}
    assert "observer_vs_participant" in names


def test_the_scenario_runs_through_the_api(client):
    created = client.post(
        "/api/experiments",
        json={"scenario": "observer_vs_participant", "params": {"ticks": 6}},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["scenario"] == "observer_vs_participant"
    experiment_id = body["study"]["experiment_id"]
    assert experiment_id > 0

    detail = client.get(f"/api/experiments/{experiment_id}").json()
    assert detail["status"] == "completed"
    assert detail["result"]["comparison"]["dimensions"]["development"]["delta"]["entities"] >= 1

    export = client.get(f"/api/experiments/{experiment_id}/export")
    assert export.status_code == 200
    assert json.loads(export.text)["result"]["scenario"] == "observer_vs_participant"


def test_word_adoption_is_recorded_on_the_timeline(inhabited_world):
    world, engine = inhabited_world
    plan = ParticipantPlan(message="stone fire", facts=(), task="", objects=())
    apply_participant_plan(world, engine.agents, plan)

    adoptions = [
        event
        for event in world.events
        if event.type == EventTypes.WORD_ADOPTED and event.actor_id == 1
    ]
    assert adoptions  # the agent's new words are on the timeline
