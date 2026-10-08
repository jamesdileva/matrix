"""The model abstraction (roadmap S07).

Everything a brain plugs into: the provider interface, the structured
decision contract, the offline mock, an OpenAI-compatible HTTP client,
and construction from settings. Nothing here imports the engine or the
database — the simulation depends on this package, never the reverse.
"""

from app.models.config import model_configuration, provider_from_settings
from app.models.decision import Decision, DecisionError, parse_decision
from app.models.mock import MockProvider
from app.models.openai_compat import OpenAICompatibleProvider
from app.models.provider import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
)

__all__ = [
    "Decision",
    "DecisionError",
    "MockProvider",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "OpenAICompatibleProvider",
    "ProviderError",
    "model_configuration",
    "parse_decision",
    "provider_from_settings",
]
