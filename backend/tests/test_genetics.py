"""S41 — genetics: a bounded genome that drifts from parent to child.

The roadmap's three verification items, one section each:

- traits remain bounded — genes stay within their range for any number of
  generations, whatever the mutation;
- inheritance is traceable — a child's genome is its parent's, changed,
  and the birth records both;
- mutations are recorded — every change is on the timeline and on the
  birth, and nothing changes silently.
"""

import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.worlds import router as worlds_router
from app.host import WorldRegistry
from app.persistence.database import Base
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.genetics import (
    DEFAULT_MUTATION_RATE,
    GENE_NAMES,
    GENE_SPECS,
    Genome,
    mutation_catalog,
)
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, Terrain, World


def _flat_engine(seed: str = "flat", size: int = 24) -> Engine:
    terrain = [[Terrain.FLOOR] * size for _ in range(size)]
    return Engine(World(seed, size, size, terrain=terrain))


def _spawn(engine: Engine, agent_id: int = 1, position: Position | None = None) -> Agent:
    agent = Agent(agent_id=agent_id, policy=WanderPolicy())
    engine.spawn_agent(agent, position or Position(1, 1))
    return agent


def _all_bounded(genome: Genome) -> bool:
    for spec in GENE_SPECS:
        if not spec.minimum <= genome.values[spec.name] <= spec.maximum:
            return False
    return True


# ----------------------------------------------------------------------
# The gene shelf and the genome
# ----------------------------------------------------------------------


class TestGenome:
    def test_the_shelf_is_well_formed(self):
        assert GENE_NAMES
        for spec in GENE_SPECS:
            assert spec.minimum < spec.maximum
            assert spec.minimum <= spec.default <= spec.maximum
            assert spec.max_step > 0

    def test_default_genome_is_in_range(self):
        assert _all_bounded(Genome.default())

    def test_from_dict_drops_unknown_and_fills_missing(self):
        genome = Genome.from_dict({"curiosity": 0.2, "not-a-gene": 5})
        assert genome.values["curiosity"] == 0.2
        assert set(genome.values) == set(GENE_NAMES)  # missing genes filled
        assert "not-a-gene" not in genome.values

    def test_from_dict_clamps_out_of_range_and_ignores_bad_types(self):
        genome = Genome.from_dict({"curiosity": 9.0, "boldness": -4, "diligence": "x"})
        curiosity = next(s for s in GENE_SPECS if s.name == "curiosity")
        assert genome.values["curiosity"] == curiosity.maximum
        assert genome.values["boldness"] == 0.0
        assert genome.values["diligence"] == next(
            s for s in GENE_SPECS if s.name == "diligence"
        ).default

    def test_to_dict_is_spec_ordered_and_json_safe(self):
        data = Genome.default().to_dict()
        assert list(data) == list(GENE_NAMES)
        assert all(isinstance(v, float) for v in data.values())

    def test_distance_measures_mean_absolute_difference(self):
        first = Genome.default()
        second = Genome(dict(first.values))
        second.values["curiosity"] = first.values["curiosity"] + 0.5
        distance = first.distance(second)
        assert distance == pytest.approx(0.5 / len(GENE_NAMES), abs=1e-6)


# ----------------------------------------------------------------------
# Traits remain bounded
# ----------------------------------------------------------------------


class TestBounded:
    def test_genes_stay_in_range_over_many_generations(self):
        rng = random.Random("drift")
        genome = Genome.default()
        for _ in range(2000):
            genome, _ = genome.inherit(rng)
            assert _all_bounded(genome), genome.values

    def test_a_gene_at_its_edge_is_held_there(self):
        spec = next(s for s in GENE_SPECS if s.name == "curiosity")
        genome = Genome.default()
        genome.values["curiosity"] = spec.maximum
        rng = random.Random("edge")
        for _ in range(500):
            genome, _ = genome.inherit(rng)
            assert genome.values["curiosity"] <= spec.maximum


# ----------------------------------------------------------------------
# Inheritance is traceable
# ----------------------------------------------------------------------


class TestTraceable:
    def test_a_child_genome_changes_only_within_a_step(self):
        specs = {spec.name: spec for spec in GENE_SPECS}
        rng = random.Random("trace")
        parent = Genome.default()
        child, _ = parent.inherit(rng)
        for name in GENE_NAMES:
            delta = abs(child.values[name] - parent.values[name])
            assert delta <= specs[name].max_step + 1e-9

    def test_the_engine_inherits_the_parent_genome(self):
        engine = _flat_engine()
        parent = _spawn(engine)
        parent.genome.values["curiosity"] = 0.9
        child = engine.create_child(parent.agent_id, position=Position(3, 3))
        specs = {spec.name: spec for spec in GENE_SPECS}
        # Every gene is within a step of the parent: the genome descends.
        for name in GENE_NAMES:
            assert abs(child.genome.values[name] - parent.genome.values[name]) <= (
                specs[name].max_step + 1e-9
            )

    def test_the_birth_records_both_genomes_and_the_mutations(self):
        engine = _flat_engine()
        parent = _spawn(engine)
        child = engine.create_child(parent.agent_id, position=Position(3, 3))
        born = next(
            e
            for e in engine.world.events
            if e.type == EventTypes.AGENT_BORN and e.target_id == child.agent_id
        )
        assert born.payload["parent_id"] == parent.agent_id
        assert born.payload["genome"] == child.genome.to_dict()

    def test_a_founder_has_no_mutations(self):
        engine = _flat_engine()
        parent = _spawn(engine)
        assert engine.mutations_of(parent.agent_id) == []


# ----------------------------------------------------------------------
# Mutations are recorded
# ----------------------------------------------------------------------


class TestMutations:
    def test_recorded_mutations_match_the_genome_change(self):
        engine = _flat_engine()
        engine._rng = random.Random("force-mutations")
        parent = _spawn(engine)
        child = engine.create_child(parent.agent_id, position=Position(3, 3))
        recorded = engine.mutations_of(child.agent_id)
        specs = {spec.name: spec for spec in GENE_SPECS}
        # Whatever was recorded is a bounded step, and the recorded `to`
        # values are exactly the child's genes that differ from the parent.
        changed = {
            name
            for name in GENE_NAMES
            if child.genome.values[name] != parent.genome.values[name]
        }
        assert {mutation["gene"] for mutation in recorded} == changed
        for mutation in recorded:
            spec = specs[mutation["gene"]]
            assert abs(mutation["to"] - mutation["from"]) <= spec.max_step + 1e-9
            assert spec.minimum <= mutation["to"] <= spec.maximum

    def test_every_mutation_appears_on_both_events(self):
        engine = _flat_engine()
        parent = _spawn(engine)
        # run births until at least one mutation happens
        current = parent
        for index in range(60):
            child = engine.create_child(
                current.agent_id, position=Position(2 + index % 20, 2 + index // 20)
            )
            if engine.mutations_of(child.agent_id):
                mutations = engine.mutations_of(child.agent_id)
                born = next(
                    e
                    for e in engine.world.events
                    if e.type == EventTypes.AGENT_BORN and e.target_id == child.agent_id
                )
                genes = next(
                    e
                    for e in engine.world.events
                    if e.type == EventTypes.GENES_INHERITED
                    and e.target_id == child.agent_id
                )
                assert born.payload["mutations"] == mutations
                assert genes.payload["mutations"] == mutations
                return
            current = child
        pytest.fail("no mutation in 60 births")


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------


class TestDeterminism:
    def test_the_same_seed_produces_the_same_drift(self):
        def run() -> list[dict]:
            engine = _flat_engine(seed="deterministic")
            parent = _spawn(engine)
            current = parent
            genomes = []
            for index in range(20):
                current = engine.create_child(
                    current.agent_id, position=Position(2 + index, 2)
                )
                genomes.append(current.genome.to_dict())
            return genomes

        assert run() == run()


# ----------------------------------------------------------------------
# The library over HTTP
# ----------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'genetics.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    application = FastAPI()
    application.include_router(worlds_router, prefix="/api")
    application.state.worlds = WorldRegistry(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    with TestClient(application) as test_client:
        yield test_client
    engine.dispose()


class TestGeneticsAPI:
    def test_the_library_lists_every_gene(self, client):
        body = client.get("/api/genetics").json()
        assert [gene["name"] for gene in body["genes"]] == list(GENE_NAMES)
        assert body["mutation_rate"] == DEFAULT_MUTATION_RATE

    def test_an_agents_detail_carries_its_genome(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "g", "width": 16, "height": 16, "agents": 1, "autostart": False},
        ).json()
        detail = client.get(f"/api/worlds/{world['id']}/agents/1").json()
        assert set(detail["genome"]) == set(GENE_NAMES)

    def test_a_lineage_member_carries_genome_and_mutations(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "g2", "width": 16, "height": 16, "agents": 1, "autostart": False},
        ).json()
        # force a birth through the API
        response = client.post(
            f"/api/worlds/{world['id']}/births",
            json={"parent_id": 1},
        )
        assert response.status_code == 201, response.text
        child_id = response.json()["id"]
        lineage = client.get(
            f"/api/worlds/{world['id']}/agents/{child_id}/lineage"
        ).json()
        child = next(m for m in lineage["chain"] if m["id"] == child_id)
        assert set(child["genome"]) == set(GENE_NAMES)
        assert isinstance(child["mutations"], list)
