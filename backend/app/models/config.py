"""Provider construction and experiment configuration.

Two jobs:

- ``provider_from_settings``: the factory turning ``FLOOD_MODEL_*``
  settings into a live provider. This is the only place provider choice
  is interpreted, so adding a provider means editing one function.
- ``model_configuration``: the JSON-safe record stamped onto every
  experiment row (guide: "model configuration is recorded with
  experiment"). Credentials are deliberately absent — experiment rows
  are shareable artifacts, and the API key never needs to leave the
  process that uses it.
"""

from __future__ import annotations

from app.config.settings import Settings, settings
from app.models.mock import MockProvider
from app.models.openai_compat import OpenAICompatibleProvider
from app.models.provider import ModelProvider

# Provider -> (default base_url, default model). "openai_compatible"
# has no defaults: both must be configured explicitly, because the
# whole point of it is pointing somewhere unusual.
_API_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://127.0.0.1:11434/v1", "llama3.1"),
}


def provider_from_settings(config: Settings | None = None) -> ModelProvider:
    """Build the provider named by the ``FLOOD_MODEL_PROVIDER`` setting."""
    config = config or settings
    name = config.model_provider
    if name == "mock":
        return MockProvider()
    if name in _API_DEFAULTS or name == "openai_compatible":
        default_base_url, default_model = _API_DEFAULTS.get(name, (None, None))
        base_url = config.model_base_url or default_base_url
        model = config.model_name or default_model
        if not base_url:
            raise ValueError(
                f"provider {name!r} needs FLOOD_MODEL_BASE_URL "
                "(no default for a generic endpoint)"
            )
        if not model:
            raise ValueError(
                f"provider {name!r} needs FLOOD_MODEL_NAME"
            )
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=model,
            api_key=config.model_api_key,
            timeout_s=config.model_timeout_s,
            temperature=config.model_temperature,
            max_tokens=config.model_max_tokens,
        )
    raise ValueError(
        f"unknown model provider {name!r}; expected one of: "
        "mock, openai, ollama, openai_compatible"
    )


def model_configuration(config: Settings | None = None) -> dict:
    """JSON-safe record of the effective model configuration.

    What actually *will* run (defaults applied), never the credential.
    """
    config = config or settings
    name = config.model_provider
    default_model = _API_DEFAULTS.get(name, (None, None))[1]
    return {
        "provider": name,
        "model": config.model_name or default_model,
        "base_url": config.model_base_url,
        "temperature": config.model_temperature,
        "max_tokens": config.model_max_tokens,
        "timeout_seconds": config.model_timeout_s,
    }
