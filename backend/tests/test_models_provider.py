"""Provider tests: the mock works offline and deterministic; the
OpenAI-compatible client posts correctly and maps every failure to
ProviderError. Transport is injected — no test touches the network."""

import asyncio
import json

import httpx
import pytest

from app.models.decision import parse_decision
from app.models.mock import MockProvider
from app.models.openai_compat import OpenAICompatibleProvider
from app.models.provider import ModelRequest, ModelResponse, ProviderError

OBSERVATION = {
    "self": {"id": 1, "position": {"x": 5, "y": 5}, "tick": 0, "goal": None},
    "cells": [{"direction": "here", "position": {"x": 5, "y": 5}, "terrain": "floor"}],
    "nearby": [],
    "inventory": [],
    "messages": [],
}


def _cells(*specs):
    """(direction, terrain, object) tuples -> observation ``cells``."""
    cells = [{"direction": "here", "position": {"x": 5, "y": 5}, "terrain": "floor"}]
    for direction, terrain, obj in specs:
        cells.append(
            {"direction": direction, "position": {"x": 5, "y": 5}, "terrain": terrain, **({"object": obj} if obj else {})}
        )
    return cells


class TestMockProvider:
    def test_emits_valid_decision_text_offline(self):
        response = asyncio.run(MockProvider().generate(ModelRequest(observation=OBSERVATION)))
        decision = parse_decision(response.text)
        assert response.provider == "mock"
        assert decision.action["action"] in {"move", "look", "pick_up"}

    def test_is_deterministic(self):
        provider = MockProvider()
        first = asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))
        second = asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))
        assert first.text == second.text

    def test_picks_up_reachable_object(self):
        observation = {
            **OBSERVATION,
            "cells": _cells(("north", "floor", {"id": 7, "type": "food"})),
        }
        response = asyncio.run(MockProvider().generate(ModelRequest(observation=observation)))
        assert parse_decision(response.text).action == {"action": "pick_up", "object_id": 7}

    def test_steps_toward_nearest_object(self):
        observation = {
            **OBSERVATION,
            "cells": _cells(("north", "floor", None), ("east", "floor", None), ("south", "floor", None), ("west", "floor", None)),
            "nearby": [
                {"kind": "object", "id": 3, "type": "tree", "position": {"x": 7, "y": 5}, "distance": 2}
            ],
        }
        response = asyncio.run(MockProvider().generate(ModelRequest(observation=observation)))
        assert parse_decision(response.text).action == {"action": "move", "direction": "east"}

    def test_looks_when_boxed_in(self):
        observation = {
            **OBSERVATION,
            "cells": _cells(("north", "wall", None), ("east", "wall", None), ("south", "water", None), ("west", "wall", None)),
        }
        response = asyncio.run(MockProvider().generate(ModelRequest(observation=observation)))
        assert parse_decision(response.text).action == {"action": "look"}


def _chat_payload(content: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestOpenAICompatibleProvider:
    def test_posts_chat_completion_and_returns_text(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_payload('{"action": {"action": "look"}}'))

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1/", model="m-1", api_key="k-123", client=_client(handler)
        )
        response = asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))

        assert parse_decision(response.text).action == {"action": "look"}
        assert seen["url"] == "http://model.test/v1/chat/completions"
        assert seen["authorization"] == "Bearer k-123"
        assert seen["body"]["model"] == "m-1"
        assert seen["body"]["messages"][0]["role"] == "system"
        assert json.loads(seen["body"]["messages"][-1]["content"]) == OBSERVATION
        assert response.provider == "openai_compatible"
        assert response.model == "m-1"
        assert response.usage["total_tokens"] == 2

    def test_generation_parameters_default_and_override(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_payload('{"action": {"action": "look"}}'))

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1", model="m", client=_client(handler)
        )
        asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))
        assert "temperature" not in seen["body"]  # unset means "provider default"
        assert "max_tokens" not in seen["body"]

        asyncio.run(
            provider.generate(ModelRequest(observation=OBSERVATION, temperature=0.9, max_tokens=32))
        )
        assert seen["body"]["temperature"] == 0.9
        assert seen["body"]["max_tokens"] == 32

    def test_request_system_prompt_overrides_default(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_payload('{"action": {"action": "look"}}'))

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1",
            model="m",
            system_prompt="be brief",
            client=_client(handler),
        )
        asyncio.run(
            provider.generate(ModelRequest(observation=OBSERVATION, system_prompt="override"))
        )
        assert seen["body"]["messages"][0] == {"role": "system", "content": "override"}

    def test_http_error_status_becomes_provider_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1", model="m", client=_client(handler)
        )
        with pytest.raises(ProviderError):
            asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))

    def test_transport_error_becomes_provider_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1", model="m", client=_client(handler)
        )
        with pytest.raises(ProviderError):
            asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))

    def test_malformed_body_becomes_provider_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1", model="m", client=_client(handler)
        )
        with pytest.raises(ProviderError):
            asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))

    def test_non_json_body_becomes_provider_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway timeout</html>")

        provider = OpenAICompatibleProvider(
            base_url="http://model.test/v1", model="m", client=_client(handler)
        )
        with pytest.raises(ProviderError):
            asyncio.run(provider.generate(ModelRequest(observation=OBSERVATION)))
