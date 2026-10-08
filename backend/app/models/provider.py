"""Model providers: the seam between a mind and the Void.

The simulation never calls a model directly. It hands a *bounded
observation* (already radius-limited by ``Agent.observe`` — never the
whole world, guide §6) to a ``ModelProvider`` and gets raw text back.
Parsing that text into a decision is ``decision.py``'s job; applying the
decision is the world's. Swapping brains — mock for tests, an
OpenAI-compatible API or a local Ollama for the real thing — means
constructing a different provider and changing nothing else (roadmap
S07: "Flood can swap brains without changing the world engine").

The interface is async by design (guide §8): model calls are network
I/O and may be slow or fail. The engine stays pure and synchronous; the
bridge that feeds providers from inside a running world lives in
``app/simulation/model_policy.py``.

Every failure mode is one exception: ``ProviderError``. Callers may then
treat "the brain said nothing usable" uniformly — which is what keeps a
broken or hostile provider from ever touching world state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(RuntimeError):
    """The provider could not produce a response.

    Raised for network failures, timeouts, HTTP errors and malformed
    responses alike, so no transport exception ever escapes into the
    simulation. Meaning: "no decision this time" — never "the world
    changed".
    """


@dataclass(frozen=True)
class ModelRequest:
    """One decision request.

    ``observation`` is the agent's bounded view (guide §6); the rest are
    generation parameters, with ``None`` meaning "provider default".
    """

    observation: dict
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    """Raw provider output.

    ``text`` is all the simulation needs; the remaining fields are
    bookkeeping for the event log and experiment records (guide §7:
    store action, rationale, observation, outcome — not private
    chain-of-thought).
    """

    text: str
    provider: str
    model: str | None = None
    usage: dict = field(default_factory=dict)


class ModelProvider(Protocol):
    """The brain seam: bounded observation in, raw text out."""

    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Return the model's raw decision text for this observation.

        Implementations must be safe to await from any event loop and
        must translate every failure into ``ProviderError``.
        """
        ...
