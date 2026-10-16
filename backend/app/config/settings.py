from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite:///./flood.db"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Model providers (S07). "mock" needs no network; "openai", "ollama"
    # and "openai_compatible" talk HTTP — the latter two differ only by
    # base_url. Construction and experiment recording: app/models/config.py.
    model_provider: str = "mock"
    model_name: str | None = None
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_temperature: float = 0.7
    model_max_tokens: int | None = 512
    model_timeout_s: float = 30.0

    # Persistence (S38). A running world autosaves every this many
    # ticks; 0 disables autosave (manual and archive snapshots still
    # work). Recovery on startup always reads the newest snapshot.
    # Only the newest `autosave_keep` autosaves are retained; manual
    # and archive snapshots are never pruned.
    autosave_every: int = 500
    autosave_keep: int = 10

    model_config = SettingsConfigDict(
        env_prefix="FLOOD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
