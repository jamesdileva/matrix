"""ModelPolicy: a Policy whose decisions come from a ModelProvider.

The ``Policy`` contract is synchronous and pure (agent.py) and the
engine must stay that way; model calls are async network I/O (guide §8).
This bridge keeps both true:

- ``refresh`` is *awaited* by whoever owns the event loop — the
  WorldHost once model agents go live (S08), tests directly — and
  stores the provider's validated decision;
- ``decide`` — called inside ``Agent.act`` on the engine's synchronous
  path — returns that stored decision, or a safe fallback when nothing
  valid is stored (provider error, invalid output, no refresh yet).

Failure semantics (roadmap S07: "provider errors do not corrupt world
state"): any failure leaves the stored decision empty. The fallback
``look`` is always legal and world-safe, so the tick completes, the
world records only the agent's own action event, and nothing else
changes. The last failure reason is kept on ``last_error`` for the
event log and debugging.

Determinism note: this is the one stateful policy — the stored decision
is transport, not memory. With a deterministic provider (MockProvider)
the simulation stays fully deterministic; with a real LLM it cannot be,
which is why replay records decisions instead of re-calling the model
(guide §"replay").
"""

from __future__ import annotations

from app.models.decision import DecisionError, parse_decision
from app.models.provider import ModelRequest, ProviderError

_FALLBACK_ACTION: dict = {"action": "look"}


class ModelPolicy:
    """Async-fed, sync-acting bridge between a provider and an Agent."""

    def __init__(
        self,
        provider,
        *,
        fallback_action: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self._fallback_action = dict(fallback_action or _FALLBACK_ACTION)
        self._decision: dict | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        """Why the last refresh produced no decision, if it didn't."""
        return self._last_error

    async def refresh(self, observation: dict) -> dict | None:
        """Ask the provider for a decision on this observation.

        Returns the validated decision dict, or None on any failure —
        after which ``decide`` falls back to the safe action.
        """
        request = ModelRequest(
            observation=observation,
            system_prompt=self.system_prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        try:
            response = await self.provider.generate(request)
        except ProviderError as exc:
            self._decision = None
            self._last_error = f"provider_error: {exc}"
            return None

        try:
            decision = parse_decision(response.text)
        except DecisionError as exc:
            self._decision = None
            self._last_error = f"invalid_decision: {exc.reason}: {exc}"
            return None

        self._decision = decision.as_dict()
        self._last_error = None
        return dict(self._decision)

    def decide(self, observation: dict) -> dict:
        """Policy.decide implementation: the stored decision, or safety.

        Returns a *decision* (``{"action": proposal, ...}``) — the shape
        ``Agent.act`` consumes — never a bare proposal.

        The ``observation`` argument is the engine's current view; the
        decision was made on the one handed to ``refresh``. At most one
        tick stale — and since every action is re-validated by the
        world, staleness can cost a rejected action, never corruption.
        """
        if self._decision is not None:
            return dict(self._decision)
        return {"action": dict(self._fallback_action)}
