"""S34 Ã¢â‚¬â€ compute efficiency: the four ratios and the budget study.

The sprint's verification Ã¢â‚¬â€ "identical scenarios can be run under
different compute budgets" Ã¢â‚¬â€ is the study class; the rest is the
machinery it rests on.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.experiments.efficiency import (
    RATIOS,
    _parse_budgets,
    _ratio,
    measure_efficiency,
    run_campaign,
    run_efficiency_study,
)
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.world import Position, Terrain, World


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'eff.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


class ReportingProvider:
    """A stub that reports usage, so the token ratio is measurable."""

    name = "reporting"
    model = "reporting-1"

    async def generate(self, request):
        from app.models.provider import ModelResponse

        return ModelResponse(
            text='{"action": {"action": "look"}}',
            provider=self.name,
            model=self.model,
            usage={"total_tokens": 100},
        )


class TestTheRatios:
    def test_no_denominator_is_not_a_zero(self):
        assert _ratio(0, 0) is None
        assert _ratio(5, 0) is None
        assert _ratio(0, 5) is None
        assert _ratio(10, 4) == 2.5

    def test_the_four_ratios_come_off_one_run(self):
        world = World(
            "ratios",
            12,
            12,
            terrain=[[Terrain.FLOOR] * 12 for _ in range(12)],
        )
        world.credit_resource(1, "wood", 2)
        world.place_object("tree", Position(1, 2), properties={"quantity": 3, "resource": "wood"})
        world.join_settlement  # attribute exists; settlement knowledge is what counts
        world.add_entity(1, Position(1, 1))
        world._add_event(
            EventTypes.INVENTION,
            actor_id=1,
            payload={"kind": "discovery", "name": "wood_axe"},
        )
        world._add_event(EventTypes.CRAFT, actor_id=1, target_id=2, payload={"recipe": "wood_axe"})
        world._add_event(EventTypes.SPEECH, actor_id=1, payload={"message": "over here"})

        world.set_budget(1, tokens=300, model_calls=3, cpu_seconds=0.5, actions=9)
        budget = world.budget_of(1)
        budget.spend("tokens", 300)
        budget.spend("model_calls", 3)
        budget.spend("cpu_seconds", 0.5)
        budget.spend("actions", 9)
        world.grant_knowledge(1, ["recipe:wood_axe"])  # the agent knows the recipe

        class _Agent:
            knowledge = ["trees give wood"]

        measures = measure_efficiency(world, [_Agent()])

        assert measures["tokens_per_discovery"] == 300.0  # one discovery
        assert measures["cpu_seconds_per_solution"] == 0.25  # two tasks
        assert measures["messages_per_successful_task"] == 0.5  # one message, two tasks
        assert measures["compute_per_surviving_concept"] == 312.5 / 2  # compute, two concepts
        assert measures["raw"]["surviving_concepts"] == 2  # the fact plus the recipe
        assert measures["raw"]["tasks"] == 2


class TestTheCampaign:
    def test_the_campaign_composes_every_measure(self, session_factory):
        record = run_campaign(session_factory=session_factory, seed="campaign", ticks=40)
        raw = record["measures"]["raw"]

        assert raw["discoveries"] >= 1
        assert raw["tasks"] >= 3
        assert raw["messages"] >= 3
        assert raw["surviving_concepts"] >= 3
        assert raw["compute"] > 0
        # The ratios that have denominators are measured; tokens and CPU
        # stay None for scripted minds, which never call a model.
        assert record["measures"]["messages_per_successful_task"] is not None
        assert record["measures"]["compute_per_surviving_concept"] is not None
        assert record["measures"]["tokens_per_discovery"] is None

    def test_the_tight_budget_accomplishes_less(self, session_factory):
        loose = run_campaign(session_factory=session_factory, seed="loose", ticks=40)
        tight = run_campaign(
            session_factory=session_factory,
            seed="tight",
            ticks=40,
            budget={"actions": 10, "model_calls": 2},
        )

        assert tight["measures"]["raw"]["tasks"] < loose["measures"]["raw"]["tasks"]
        assert tight["measures"]["raw"]["compute"] < loose["measures"]["raw"]["compute"]

    def test_a_model_minded_campaign_reports_tokens(self, session_factory, monkeypatch):
        from app.experiments import efficiency

        monkeypatch.setattr(efficiency.settings, "model_provider", "mock")
        # The campaign reads the provider factory lazily, so patch it
        # where it is imported from.
        import app.models.config as config

        monkeypatch.setattr(config, "provider_from_settings", lambda settings: ReportingProvider())
        record = run_campaign(
            session_factory=session_factory, mode="model", seed="model", ticks=6
        )

        raw = record["measures"]["raw"]
        assert raw["model_calls"] > 0
        if raw["discoveries"]:
            assert record["measures"]["tokens_per_discovery"] is not None

    def test_the_campaign_is_deterministic(self, session_factory):
        first = run_campaign(session_factory=session_factory, seed="same", ticks=40)
        second = run_campaign(session_factory=session_factory, seed="same", ticks=40)

        assert first["measures"] == second["measures"]


class TestTheStudy:
    def test_identical_scenarios_under_different_budgets(self, session_factory):
        study = run_efficiency_study(
            session_factory=session_factory, seed="study", ticks=40
        )

        assert [run["label"] for run in study["runs"]] == ["unconstrained", "tight"]
        # The scenario is the same; only the budget differs, so the
        # comparison is apples to apples Ã¢â‚¬â€ and the tight run did less.
        accomplished = study["comparison"]["accomplished"]
        assert accomplished["tight"]["tasks"] <= accomplished["unconstrained"]["tasks"]
        assert set(study["comparison"]["ratios"]) == set(RATIOS)
        for table in study["comparison"]["ratios"].values():
            assert set(table["per_run"]) == {"unconstrained", "tight"}

    def test_named_budgets_are_comparable(self, session_factory):
        study = run_efficiency_study(
            session_factory=session_factory,
            seed="named",
            ticks=20,
            budgets=[{"label": "free"}, {"label": "starved", "actions": 6}],
        )

        rows = {run["label"]: run for run in study["runs"]}
        assert rows["starved"]["budget"] == {"actions": 6}
        assert rows["free"]["budget"] == {}
        ratios = study["comparison"]["ratios"]["messages_per_successful_task"]["per_run"]
        assert set(ratios) == {"free", "starved"}
        assert ratios["free"] is not None

    def test_the_study_rows_complete(self, session_factory):
        study = run_efficiency_study(session_factory=session_factory, seed="rows", ticks=10)

        with session_factory() as session:
            study_row = session.get(ExperimentModel, study["experiment_id"])
            assert study_row.status == "completed"
            assert study_row.scenario == "efficiency_study"
            run_ids = study_row.model_configuration["run_experiment_ids"]
            assert len(run_ids) == 2
            for run_id in run_ids:
                assert session.get(ExperimentModel, run_id).status == "completed"

    def test_the_export_round_trips(self, session_factory, tmp_path):
        path = tmp_path / "study.json"
        study = run_efficiency_study(
            session_factory=session_factory, seed="export", ticks=10, export_path=str(path)
        )

        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["scenario"] == "efficiency_study"
        assert reloaded["ratios"] == list(RATIOS)
        assert len(reloaded["runs"]) == 2
        assert reloaded["comparison"]["accomplished"]["unconstrained"]["tasks"] >= 1
        assert study["export_path"] == str(path)

    def test_the_cli_parses_budget_lists(self):
        budgets = _parse_budgets("unconstrained;tight:model_calls=2,actions=12")

        assert budgets == [
            {"label": "unconstrained"},
            {"label": "tight", "model_calls": 2.0, "actions": 12.0},
        ]
        assert _parse_budgets(None) is None
        assert _parse_budgets("open:") == [{"label": "open"}]


class TestBadRequests:
    def test_a_study_needs_distinct_labels(self, session_factory):
        with pytest.raises(ValueError, match="distinct label"):
            run_efficiency_study(
                session_factory=session_factory, budgets=[{"label": "a"}, {"label": "a"}]
            )

    def test_every_budget_needs_a_label(self, session_factory):
        with pytest.raises(ValueError, match="distinct label"):
            run_efficiency_study(
                session_factory=session_factory, budgets=[{"label": "a"}, {"actions": 3}]
            )

    def test_unknown_modes_are_refused(self, session_factory):
        with pytest.raises(ValueError, match="unknown mode"):
            run_campaign(session_factory=session_factory, mode="shout")
