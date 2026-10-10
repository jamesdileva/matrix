"""S21 — human-agent conversation: local speech, targeting, replies.

The roadmap's check is "human sends a message to an agent and receives
a model-generated response" — so these tests drive the real chain
against a live backend: the participant speaks, the target agent's
observation carries the message, and a model mind replies through the
same decision contract that carries its actions.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.host import PARTICIPANT_ENTITY_ID, WorldRegistry
from app.models.provider import ModelResponse
from app.persistence.database import Base
from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.model_policy import ModelPolicy
from app.simulation.world import Position, World
from app.simulation.events import EventTypes


class EchoProvider:
    """Replies to whatever was said, proving the message was heard."""

    name = "echo"
    model = "echo-1"

    async def generate(self, request):
        heard = request.observation.get("messages", [])
        if heard:
            text = (
                '{"action": {"action": "look"}, '
                f'"message": "you said: {heard[0]["message"]}"}}'
            )
        else:
            text = '{"action": {"action": "look"}}'
        return ModelResponse(text=text, provider=self.name, model=self.model)


@pytest.fixture()
def app(tmp_path, monkeypatch):
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
    # Worlds with model brains get the echo provider.
    import app.host as host_module

    monkeypatch.setattr(host_module, "provider_from_settings", lambda config=None: EchoProvider())
    yield application, engine
    asyncio.run(application.state.worlds.stop_all())
    engine.dispose()


@pytest.fixture()
def client(app):
    application, _ = app
    with TestClient(application) as test_client:
        yield test_client


def _model_world(client) -> dict:
    response = client.post(
        "/api/worlds",
        json={"seed": "matrix", "width": 24, "height": 24, "agents": 1,
              "autostart": False, "brains": "model"},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestSpeech:
    def test_say_records_a_speech_event(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        client.post(f"/api/worlds/{world['id']}/participant/join")

        said = client.post(
            f"/api/worlds/{world['id']}/participant/move", json={"direction": "east"}
        ).json()  # move somewhere with room, then speak below
        speech = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": PARTICIPANT_ENTITY_ID, "action": {"action": "say", "message": "hello void"}},
        ).json()

        assert speech["ok"] is True
        events = client.get(f"/api/worlds/{world['id']}/events?since_id=0").json()["events"]
        speeches = [e for e in events if e["type"] == "SPEECH"]
        assert len(speeches) == 1
        assert speeches[0]["payload"]["message"] == "hello void"
        assert speeches[0]["actor_id"] == PARTICIPANT_ENTITY_ID

    def test_empty_message_rejected(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        client.post(f"/api/worlds/{world['id']}/participant/join")
        result = client.post(
            f"/api/worlds/{world['id']}/actions",
            json={"agent_id": PARTICIPANT_ENTITY_ID, "action": {"action": "say", "message": "   "}},
        ).json()
        assert result["ok"] is False
        assert result["reason"] == "empty_message"

    def test_hearing_is_local(self):
        from app.simulation.world import Terrain

        world = World(
            "t", 24, 24, terrain=[[Terrain.FLOOR] * 24 for _ in range(24)]
        )
        engine = Engine(world)
        near = Agent(agent_id=1, policy=_Noop())
        far = Agent(agent_id=2, policy=_Noop())
        speaker = Agent(agent_id=3, policy=_Noop())
        engine.spawn_agent(near, Position(5, 5))
        engine.spawn_agent(far, Position(20, 20))
        engine.spawn_agent(speaker, Position(6, 5))

        world.say(3, "can you hear me")

        # The near agent hears it in its observation; the far one does
        # not; and nobody hears themselves.
        heard = [m for m in near.observe()["messages"] if m["from"] == 3]
        assert len(heard) == 1
        assert heard[0]["message"] == "can you hear me"
        assert world.messages_for(2) == []
        assert world.messages_for(3) == []
        assert world.messages_for(20) == []  # not even in the world

    def test_speech_buffer_is_bounded(self):
        from app.simulation.world import SPEECH_BUFFER, Terrain

        world = World(
            "t", 24, 24, terrain=[[Terrain.FLOOR] * 24 for _ in range(24)]
        )
        engine = Engine(world)
        speaker = Agent(agent_id=1, policy=_Noop())
        late = Agent(agent_id=2, policy=_Noop())
        engine.spawn_agent(speaker, Position(5, 5))
        for index in range(SPEECH_BUFFER + 10):
            world.say(1, f"line {index}")
        assert world.messages_for(1) == []  # you never hear yourself
        # A later listener hears only the most recent window of it.
        engine.spawn_agent(late, Position(6, 5))
        messages = late.observe()["messages"]
        assert len(messages) == SPEECH_BUFFER
        assert messages[0]["message"] == "line 10"


class _Noop:
    def decide(self, observation: dict) -> dict:
        return {"action": {"action": "look"}}


class TestConversation:
    def test_human_sends_message_and_receives_model_reply(self, client):
        world = _model_world(client)
        client.post(f"/api/worlds/{world['id']}/participant/join")

        chat = client.post(
            f"/api/worlds/{world['id']}/chat",
            json={"agent_id": 1, "message": "who are you?"},
        ).json()

        assert chat["heard"] is True
        assert chat["reply"] == "you said: who are you?"
        assert chat["reply_event_id"] is not None

        # Both utterances are on the timeline, and the log sees them.
        conversations = client.get(f"/api/worlds/{world['id']}/conversations").json()[
            "conversations"
        ]
        assert [c["message"] for c in conversations] == ["who are you?", "you said: who are you?"]
        assert conversations[0]["kind"] == "participant"
        assert conversations[1]["kind"] == "agent"

    def test_chat_without_joining_is_rejected(self, client):
        world = _model_world(client)
        response = client.post(
            f"/api/worlds/{world['id']}/chat",
            json={"agent_id": 1, "message": "hello?"},
        )
        assert response.status_code == 409

    def test_out_of_earshot_is_rejected(self, client):
        world = _model_world(client)
        client.post(f"/api/worlds/{world['id']}/participant/join")
        # The founder spawns at (1,1) and the participant elsewhere;
        # push the participant far away with moves is slow — instead
        # place a fresh world's agent far from the participant.
        host = client.app.state.worlds.get(world["id"])  # type: ignore[attr-defined]
        agent_position = host.engine.agents[0].position
        host.engine.world.remove_entity(PARTICIPANT_ENTITY_ID)
        far = Position(agent_position.x + 12, agent_position.y + 12)
        host.engine.world.add_entity(PARTICIPANT_ENTITY_ID, far)
        response = client.post(
            f"/api/worlds/{world['id']}/chat",
            json={"agent_id": 1, "message": "can you hear me?"},
        )
        assert response.status_code == 400
        assert "earshot" in response.json()["detail"]

    def test_unknown_agent_is_404(self, client):
        world = _model_world(client)
        client.post(f"/api/worlds/{world['id']}/participant/join")
        response = client.post(
            f"/api/worlds/{world['id']}/chat",
            json={"agent_id": 99, "message": "hello?"},
        )
        assert response.status_code == 404

    def test_scripted_agent_records_speech_without_reply(self, client):
        world = client.post(
            "/api/worlds",
            json={"seed": "matrix", "width": 24, "height": 24, "agents": 1, "autostart": False},
        ).json()
        client.post(f"/api/worlds/{world['id']}/participant/join")

        chat = client.post(
            f"/api/worlds/{world['id']}/chat",
            json={"agent_id": 1, "message": "hello there"},
        ).json()

        assert chat["heard"] is True
        assert chat["reply"] is None  # a scripted mind has nothing to say
        conversations = client.get(f"/api/worlds/{world['id']}/conversations").json()[
            "conversations"
        ]
        assert [c["message"] for c in conversations] == ["hello there"]
