"""An OpenAI-compatible chat-completions provider.

One implementation covers OpenAI-style APIs and local servers because
the only difference is ``base_url`` — Ollama exposes an
OpenAI-compatible endpoint at ``/v1``, and so do vLLM, llama.cpp and
friends. That is exactly why the roadmap asks for an abstraction
instead of a hardwired client.

Transport is injectable: tests pass an ``httpx.AsyncClient`` backed by
a ``MockTransport`` and never touch the network.

Failure policy (roadmap S07: "provider errors do not corrupt world
state"): network errors, timeouts, HTTP error statuses and malformed
response bodies all become ``ProviderError``. Callers treat that as
"no decision this time" — a broken brain leaves the world untouched.
"""

from __future__ import annotations

import json

import httpx

from app.models.provider import (
    ModelRequest,
    ModelResponse,
    ProviderError,
)

DEFAULT_TIMEOUT_S = 30.0

DEFAULT_SYSTEM_PROMPT = (
    "You are an agent inside a small grid world. Decide your next action "
    "from the observation. Reply with JSON only, in this shape: "
    '{"action": {"action": "move|look|inspect|pick_up|drop|place", '
    '"direction": "north|south|east|west"}, '
    '"goal_update": string|null, "thought_summary": string|null}. '
    "The world validates every action; an illegal action is rejected "
    "and never changes the world."
)


class OpenAICompatibleProvider:
    """POST chat-completions to any OpenAI-compatible endpoint."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s)
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": self.model,
            "messages": self._messages(request),
            "temperature": _first_not_none(request.temperature, self.temperature),
            "max_tokens": _first_not_none(request.max_tokens, self.max_tokens),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            # Transport/HTTP failures, non-JSON bodies, unexpected shape.
            # The exception type is always named: some httpx failures
            # (timeouts above all) stringify to nothing, and an empty
            # reason in the event log is a debugging dead end.
            raise ProviderError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        if not isinstance(text, str):
            raise ProviderError(f"{self.name}: response content is not text")
        return ModelResponse(
            text=text,
            provider=self.name,
            model=self.model,
            usage=data.get("usage") or {},
        )

    def _messages(self, request: ModelRequest) -> list[dict]:
        messages = []
        system_prompt = _first_not_none(request.system_prompt, self.system_prompt)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {"role": "user", "content": json.dumps(request.observation)}
        )
        return messages

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None
