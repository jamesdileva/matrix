import json

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings
from app.models.config import model_configuration, provider_from_settings
from app.models.mock import MockProvider
from app.models.openai_compat import OpenAICompatibleProvider
from app.persistence.models import ExperimentModel
from app.persistence.repositories import ExperimentRepository


class TestProviderFromSettings:
    def test_defaults_to_mock(self):
        assert isinstance(provider_from_settings(Settings(_env_file=None)), MockProvider)

    def test_openai_defaults(self):
        provider = provider_from_settings(Settings(_env_file=None, model_provider="openai"))
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://api.openai.com/v1"
        assert provider.model == "gpt-4o-mini"

    def test_ollama_defaults(self):
        provider = provider_from_settings(Settings(_env_file=None, model_provider="ollama"))
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "http://127.0.0.1:11434/v1"
        assert provider.model == "llama3.1"

    def test_openai_compatible_requires_explicit_config(self):
        with pytest.raises(ValueError, match="FLOOD_MODEL_BASE_URL"):
            provider_from_settings(Settings(_env_file=None, model_provider="openai_compatible"))
        with pytest.raises(ValueError, match="FLOOD_MODEL_NAME"):
            provider_from_settings(
                Settings(
                    _env_file=None,
                    model_provider="openai_compatible",
                    model_base_url="http://localhost:9000/v1",
                )
            )

    def test_openai_compatible_with_explicit_config(self):
        provider = provider_from_settings(
            Settings(
                _env_file=None,
                model_provider="openai_compatible",
                model_base_url="http://localhost:9000/v1/",
                model_name="local-7b",
                model_api_key="secret",
                model_temperature=0.3,
                model_max_tokens=99,
                model_timeout_s=5,
            )
        )
        assert provider.base_url == "http://localhost:9000/v1"  # trailing slash trimmed
        assert provider.model == "local-7b"
        assert provider.temperature == 0.3
        assert provider.max_tokens == 99
        assert provider.timeout_s == 5

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValueError, match="unknown model provider"):
            provider_from_settings(Settings(_env_file=None, model_provider="telepathy"))


class TestModelConfiguration:
    def test_effective_configuration_recorded(self):
        config = model_configuration(Settings(_env_file=None, model_provider="ollama"))
        assert config["provider"] == "ollama"
        assert config["model"] == "llama3.1"  # default applied, not None
        assert config["temperature"] == 0.7

    def test_configuration_is_json_safe_and_holds_no_secrets(self):
        config = Settings(
            _env_file=None,
            model_provider="openai",
            model_name="gpt-test",
            model_api_key="sk-super-secret",
        )
        recorded = model_configuration(config)
        text = json.dumps(recorded)  # must be JSON-serializable for the DB column
        assert "sk-super-secret" not in text
        assert "api_key" not in recorded
        assert recorded["provider"] == "openai"
        assert recorded["model"] == "gpt-test"


class TestExperimentRepository:
    def test_create_stamps_active_model_configuration(self, db_engine):
        factory = sessionmaker(bind=db_engine, expire_on_commit=False)
        repo = ExperimentRepository(factory)

        experiment_id = repo.create(name="lineage-1", scenario="lineage_drift", seed="matrix")

        with Session(db_engine) as session:
            row = session.get(ExperimentModel, experiment_id)
            assert row.name == "lineage-1"
            assert row.status == "created"
            # The default mock provider's configuration, no secrets.
            assert row.model_configuration["provider"] == "mock"
            assert "api_key" not in row.model_configuration

    def test_create_accepts_explicit_configuration_and_budget(self, db_engine):
        factory = sessionmaker(bind=db_engine, expire_on_commit=False)
        repo = ExperimentRepository(factory)

        experiment_id = repo.create(
            name="llm-run",
            scenario="first_llm_agent",
            seed="void",
            model_configuration={"provider": "ollama", "model": "llama3.1"},
            compute_budget={"max_model_calls": 100, "max_tokens": 10000},
            generation_limit=50,
        )

        with Session(db_engine) as session:
            row = session.get(ExperimentModel, experiment_id)
            assert row.model_configuration == {"provider": "ollama", "model": "llama3.1"}
            assert row.compute_budget == {"max_model_calls": 100, "max_tokens": 10000}
            assert row.generation_limit == 50
