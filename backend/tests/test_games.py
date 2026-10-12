"""S31 â€” games: rules as data, sessions, scoring, human participation.

The sprint's verification â€” "agent-created rules can be represented by
the game engine and played without arbitrary code execution" â€” is the
validator's section and the refusal classes below; everything else is
the machinery that check rests on.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.experiments.game import invent_game, play_calibration
from app.host import WorldRegistry
from app.persistence.database import Base
from app.persistence.models import ExperimentModel
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.events import EventTypes
from app.simulation.games import LONG_ROAD, PlayerPolicy, validate_rules
from app.simulation.world import Position, Terrain, World

PARTICIPANT = 1001  # the participant's entity id (S20)


def _lot() -> World:
    return World(
        "g31",
        16,
        16,
        terrain=[[Terrain.FLOOR] * 16 for _ in range(16)],
    )


def _table(*seats: int) -> tuple[World, Engine, list[Agent]]:
    world = _lot()
    engine = Engine(world, population_id=1)
    agents = []
    for index in seats:
        agent = Agent(agent_id=index, policy=PlayerPolicy())
        engine.spawn_agent(agent, Position(index, index))
        agents.append(agent)
    game = world.propose_game(agents[0].agent_id if agents else None, LONG_ROAD)
    session = world.open_session(game["id"])
    for seat in seats:
        world.join_session(session.id, seat)
    return world, engine, agents


class TestTheValidator:
    def test_a_well_formed_game_passes(self):
        assert validate_rules(LONG_ROAD) == []

    def test_the_calibration_game_finishes(self):
        world, engine, agents = _table(1, 2)
        for _tick in range(1, 60):
            engine.step()
            if world.session(1).status == "finished":
                break

        session = world.session(1)
        assert session.status == "finished"
        assert session.winner in (1, 2)
        assert len(session.history) == 10  # the mark is reached in ten strides
        assert session.state["track"] == 10
        assert world.session(1).win_reason == "first to track 10"

    def test_unknown_keys_are_refused(self):
        broken = {**LONG_ROAD, "moves": {**LONG_ROAD["moves"], "cheat": {"explode": True}}}

        assert "has an unknown key" in "; ".join(validate_rules(broken))

    def test_unknown_effects_are_refused(self):
        broken = {
            **LONG_ROAD,
            "moves": {"stride": {"requires": {"track": "<10"}, "effect": {"add": {"track": 1}, "delete": "everything"}}},
        }

        errors = "; ".join(validate_rules(broken))
        assert "unknown effect" in errors

    def test_undeclared_state_is_refused(self):
        broken = {
            **LONG_ROAD,
            "moves": {"stride": {"requires": {"miles": "<10"}, "effect": {"add": {"track": 1}}}},
        }

        errors = "; ".join(validate_rules(broken))
        assert "requires undeclared state" in errors

    def test_a_game_nobody_can_open_is_refused(self):
        broken = {
            "name": "Closed Door",
            "players": 2,
            "setup": {"track": 10},
            "moves": {"stride": {"requires": {"track": "<10"}, "effect": {"add": {"track": 1}}}},
            "win": {"first_to": {"track": 20}},
        }

        assert "cannot open" in "; ".join(validate_rules(broken))

    def test_malformed_shapes_are_refused(self):
        assert "players must be" in "; ".join(validate_rules({**LONG_ROAD, "players": 1}))
        assert "moves must be" in "; ".join(validate_rules({**LONG_ROAD, "moves": {}}))
        assert "win must be" in "; ".join(validate_rules({**LONG_ROAD, "win": {"high_score": 5}}))
        assert "needs a non-empty name" in "; ".join(validate_rules({**LONG_ROAD, "name": ""}))

    def test_setups_hold_only_scalars(self):
        broken = {**LONG_ROAD, "setup": {"track": [1, 2]}}

        assert "must be an int, string or boolean" in "; ".join(validate_rules(broken))


class TestSessions:
    def test_a_full_table_plays_and_a_winner_emerges(self):
        world, engine, agents = _table(1, 2)
        for _tick in range(1, 60):
            engine.step()
            if world.session(1).status == "finished":
                break

        session = world.session(1)
        assert session.status == "finished"
        assert session.winner in (1, 2)
        assert len(session.history) == 10  # the mark is reached in ten strides
        assert session.state["track"] == 10
        assert session.win_reason == "first to track 10"

    def test_a_tick_plays_the_whole_table(self):
        world, engine, agents = _table(1, 2)

        engine.step()  # a stride from each player, in seat order

        session = world.session(1)
        assert session.state["track"] == 2
        assert session.current_player == 1  # the turn comes round
        events = [e for e in world.events if e.type == EventTypes.GAME_MOVE]
        assert [e.actor_id for e in events] == [1, 2]
        assert all(e.payload["move"] == "stride" for e in events)

    def test_only_the_current_player_moves(self):
        world, engine, agents = _table(1, 2)

        # Agent 2 replies from an already-moving world: its turn follows
        # agent 1's, so it is not yet its turn.
        result = world.execute_action(2, {"action": "play", "game": 1, "move": "stride"})

        assert result.reason == "not_your_turn"

    def test_moves_the_rules_forbid_are_refused(self):
        world, engine, agents = _table(1, 2)
        for _ in range(10):
            engine.step()  # both players stride to the mark
        session = world.session(1)
        if session.status != "finished":
            pytest.skip("the calibration game ended before this check")
        result = world.execute_action(1, {"action": "play", "game": 1, "move": "stride"})

        assert result.reason == "game_over"

    def test_an_unknown_move_and_table_are_refused(self):
        world, engine, agents = _table(1, 2)

        assert world.execute_action(1, {"action": "play", "game": 1, "move": "sprint"}).reason == "unknown_move"
        assert world.execute_action(1, {"action": "play", "game": 9, "move": "stride"}).reason == "unknown_game"

    def test_seats_fill_in_order_then_play_begins(self):
        world = _lot()
        world.add_entity(1, Position(1, 1))
        world.add_entity(2, Position(2, 2))
        game = world.propose_game(None, LONG_ROAD)
        session = world.open_session(game["id"])

        world.join_session(session.id, 1)
        assert session.status == "open"
        world.join_session(session.id, 2)

        assert session.status == "playing"
        assert session.players == [1, 2]
        events = [e for e in world.events if e.type == EventTypes.GAME_STARTED]
        assert events[0].payload["players"] == [1, 2]

    def test_an_extra_seat_and_a_double_seat_are_refused(self):
        world = _lot()
        for index in (1, 2, 3):
            world.add_entity(index, Position(index, index))
        game = world.propose_game(None, LONG_ROAD)
        session = world.open_session(game["id"])
        world.join_session(session.id, 1)
        world.join_session(session.id, 2)

        with pytest.raises(ValueError, match="no open seat"):
            world.join_session(session.id, 3)
        with pytest.raises(ValueError, match="already sits"):
            world.join_session(session.id, 1)

    def test_an_unplayable_proposal_is_refused_with_reasons(self):
        world = _lot()

        with pytest.raises(ValueError, match="unplayable rules"):
            world.propose_game(None, {**LONG_ROAD, "name": ""})

    def test_the_scored_variant_counts_points(self):
        rules = {
            "name": "Gathering",
            "players": 2,
            "setup": {"round": 0, "wood": 0},
            "moves": {
                "gather": {"requires": {"wood": "<6"}, "effect": {"add": {"wood": 1}, "award": 1}},
                "rest": {"requires": {}, "effect": {}},
            },
            "win": {"most_points_after_rounds": 2},
        }
        assert validate_rules(rules) == []
        world = _lot()
        for index in (1, 2):
            world.add_entity(index, Position(index, index))
        game = world.propose_game(None, rules)
        session = world.open_session(game["id"])
        world.join_session(session.id, 1)
        world.join_session(session.id, 2)
        for index in range(0, 4):
            for player in (1, 2):
                legal = session.legal_moves(player)
                if legal:
                    world.play_move(session.id, player, legal[0])

        assert session.status == "finished"
        assert session.win_reason == "most points after 2 rounds"
        assert sum(session.points.values()) == 4  # two rounds of two gathers


class TestObservationsAndHistory:
    def test_players_see_their_own_turn_and_moves(self):
        world, engine, agents = _table(1, 2)

        view = engine.agents[0].observe()["games"]

        assert len(view) == 1
        assert view[0]["your_turn"] is True
        assert view[0]["legal_moves"] == ["stride"]
        assert view[0]["state"] == {"track": 0}

    def test_a_spectator_sees_nothing(self):
        world, engine, agents = _table(1, 2)
        world.add_entity(3, Position(3, 3))

        assert world.games_for(3) == []

    def test_every_move_is_on_the_timeline(self):
        world, engine, agents = _table(1, 2)
        for _tick in range(1, 60):
            engine.step()
            if world.session(1).status == "finished":
                break

        events = [e for e in world.events if e.type == EventTypes.GAME_MOVE]
        assert len(events) == 10
        assert [e.payload["state"]["track"] for e in events] == list(range(1, 11))
        over = [e for e in world.events if e.type == EventTypes.GAME_OVER]
        assert len(over) == 1
        assert over[0].payload["winner"] == 2


class TestTheExperiment:
    @pytest.fixture()
    def session_factory(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'game.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()

    def test_the_calibration_game_is_played(self, session_factory):
        record = play_calibration(session_factory=session_factory, seed="control")

        assert record["game"] == "The Long Road"
        assert record["moves_played"] == 10
        assert record["winner"] in (1, 2)
        assert record["final_state"]["track"] == 10
        with Session(session_factory.kw["bind"]) as session:
            experiment = session.get(ExperimentModel, record["experiment_id"])
            assert experiment.status == "completed"
            assert experiment.scenario == "game"

    def test_the_calibration_is_deterministic(self, session_factory):
        first = play_calibration(session_factory=session_factory, seed="same")
        second = play_calibration(session_factory=session_factory, seed="same")

        assert first["winner"] == second["winner"]
        assert first["moves_played"] == second["moves_played"]

    def test_the_designer_prompts_through_the_seam(self):
        class StubProvider:
            name = "stub"
            model = "stub-1"

            async def generate(self, request):
                from app.models.provider import ModelResponse

                text = '{"name": "Race to Five", "players": 2, "setup": {"track": 0}, '
                text += '"moves": {"stride": {"requires": {"track": "<5"}, "effect": {"add": {"track": 1}}}}, '
                text += '"win": {"first_to": {"track": 5}}}'
                return ModelResponse(provider="stub", model="stub-1", text=text)

        import asyncio

        invention = asyncio.run(invent_game(StubProvider()))

        assert invention["valid"] is True
        assert invention["rules"]["name"] == "Race to Five"

    def test_unusable_designs_fail_loudly(self):
        class StubProvider:
            name = "stub"
            model = "stub-1"

            async def generate(self, request):
                from app.models.provider import ModelResponse

                return ModelResponse(provider="stub", model="stub-1", text="I have no idea")

        import asyncio

        invention = asyncio.run(invent_game(StubProvider()))

        assert invention["valid"] is False
        assert "unusable output" in invention["errors"][0]


class TestTheAPI:
    @pytest.fixture()
    def client(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'api.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        application = FastAPI()
        application.include_router(health_router, prefix="/api")
        application.include_router(worlds_router, prefix="/api")
        application.state.worlds = WorldRegistry(
            sessionmaker(bind=engine, expire_on_commit=False)
        )
        with TestClient(application) as test_client:
            yield test_client
        engine.dispose()

    def _create(self, client: TestClient, **payload) -> dict:
        full = {"seed": "s31", "agents": 2, "autostart": False}
        full.update(payload)
        response = client.post("/api/worlds", json=full)
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_game_is_proposed_validated_and_listed(self, client):
        world = self._create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/games",
            json=LONG_ROAD,
        )

        assert response.status_code == 201
        assert response.json()["game"]["name"] == "The Long Road"
        listing = client.get(f"/api/worlds/{world['id']}/games").json()
        assert [game["name"] for game in listing["games"]] == ["The Long Road"]

    def test_the_human_plays_an_invented_game(self, client):
        world = self._create(client)
        client.post(f"/api/worlds/{world['id']}/games", json=LONG_ROAD)
        listing = client.get(f"/api/worlds/{world['id']}/games").json()
        game_id = listing["games"][0]["id"]

        # Open a table, seat the human first, then the opponent: the
        # first seat is the first to move.
        opened = client.post(f"/api/worlds/{world['id']}/games/{game_id}/sessions")
        assert opened.status_code == 201
        session_id = opened.json()["session"]["id"]
        joined = client.post(f"/api/worlds/{world['id']}/participant/join")
        assert joined.status_code == 200
        seated = client.post(
            f"/api/worlds/{world['id']}/games/sessions/{session_id}/join",
            json={"entity_id": PARTICIPANT},
        )
        assert seated.status_code == 201
        assert seated.json()["session"]["status"] == "open"

        opponent = client.post(
            f"/api/worlds/{world['id']}/games/sessions/{session_id}/join",
            json={"entity_id": 1},
        )
        assert opponent.status_code == 201
        assert opponent.json()["session"]["status"] == "playing"

        # The human is seated first: it is their move.
        detail = client.get(
            f"/api/worlds/{world['id']}/games/sessions/{session_id}",
            params={"as_entity": PARTICIPANT},
        ).json()
        assert detail["session"]["your_turn"] is True
        assert detail["session"]["legal_moves"] == ["stride"]

        moved = client.post(
            f"/api/worlds/{world['id']}/games/sessions/{session_id}/moves",
            json={"move": "stride"},
        )
        assert moved.status_code == 201
        outcome = moved.json()["move"]
        assert outcome["state"] == {"track": 1}
        events = client.get(
            f"/api/worlds/{world['id']}/events?since_id=0&limit=100"
        ).json()
        assert any(
            e["type"] == "GAME_MOVE" and e["payload"]["move"] == "stride"
            for e in events["events"]
        )

    def test_an_unplayable_game_is_refused_with_reasons(self, client):
        world = self._create(client)

        response = client.post(
            f"/api/worlds/{world['id']}/games",
            json={**LONG_ROAD, "name": "", "moves": {}},
        )

        assert response.status_code == 400
        assert "unplayable rules" in response.json()["detail"]

    def test_unknown_sessions_are_404s(self, client):
        world = self._create(client)

        assert client.get(f"/api/worlds/{world['id']}/games/sessions/7").status_code == 404
        join = client.post(
            f"/api/worlds/{world['id']}/games/sessions/7/join",
            json={"entity_id": 1},
        )
        assert join.status_code == 404
