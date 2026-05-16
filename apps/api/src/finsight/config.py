"""Centralized application configuration.

All environment variables are loaded, validated, and exposed through a single
`Settings` instance. Modules should import `get_settings()` rather than reading
`os.environ` directly.

Usage:
    from finsight.config import get_settings

    settings = get_settings()
    qdrant_url = settings.qdrant.url
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Enums for constrained string fields. Using enums (vs raw strings) gives us
# autocomplete, type-checking, and clear error messages on invalid values.
# ---------------------------------------------------------------------------


class AppEnv(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Standard logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogFormat(StrEnum):
    """Log output format. Use 'console' locally, 'json' in production."""

    CONSOLE = "console"
    JSON = "json"


# ---------------------------------------------------------------------------
# Resolve the project root so we can locate the .env file regardless of where
# the app is started from (uv run, docker, pytest, etc.).
# This file lives at: <root>/apps/api/src/finsight/config.py
# So the root is four levels up.
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]
ENV_FILE: Path = PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# Grouped settings — one class per logical concern.
# Each group can be nested inside the main Settings object via env_prefix.
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    name: str = "finsight"
    env: AppEnv = AppEnv.DEVELOPMENT
    debug: bool = True
    log_level: LogLevel = LogLevel.INFO
    log_format: LogFormat = LogFormat.CONSOLE


class APISettings(BaseSettings):
    """FastAPI server configuration."""

    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    host: str = "0.0.0.0"  # noqa: S104  (binding 0.0.0.0 is intentional for Docker)
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Accept either a comma-separated string or a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


class LLMSettings(BaseSettings):
    """LLM provider keys and model selection."""

    model_config = SettingsConfigDict(extra="ignore")

    # Provider keys — SecretStr prevents accidental logging.
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    cohere_api_key: SecretStr | None = Field(default=None, alias="COHERE_API_KEY")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    together_api_key: SecretStr | None = Field(default=None, alias="TOGETHER_API_KEY")

    # Model selection
    provider: Literal["openai", "anthropic", "groq", "ollama"] = Field(
        default="anthropic", alias="LLM_PROVIDER"
    )
    model: str = Field(default="claude-sonnet-4-5", alias="LLM_MODEL")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, alias="LLM_TEMPERATURE")


class EmbeddingSettings(BaseSettings):
    """Embedding model configuration."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")

    provider: Literal["openai", "cohere", "local"] = "openai"
    model: str = "text-embedding-3-large"
    dimensions: int = Field(default=3072, ge=1)


class RerankerSettings(BaseSettings):
    """Reranker configuration."""

    model_config = SettingsConfigDict(env_prefix="RERANKER_", extra="ignore")

    provider: Literal["cohere", "bge", "mxbai"] = "cohere"
    model: str = "rerank-english-v3.0"


class QdrantSettings(BaseSettings):
    """Qdrant vector store connection."""

    model_config = SettingsConfigDict(env_prefix="QDRANT_", extra="ignore")

    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None
    collection: str = "finsight_chunks"


class PostgresSettings(BaseSettings):
    """PostgreSQL connection."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    db: str = "finsight"
    user: str = "finsight"
    password: SecretStr = SecretStr("change-this-in-production")

    @property
    def dsn(self) -> str:
        """Async SQLAlchemy connection string."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    """Redis connection."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = Field(default=6379, ge=1, le=65535)
    url: str = "redis://localhost:6379/0"


class LangfuseSettings(BaseSettings):
    """Langfuse observability platform."""

    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", extra="ignore")

    public_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    host: str = "http://localhost:3001"

    @property
    def enabled(self) -> bool:
        """Langfuse is active only when both keys are set."""
        return self.public_key is not None and self.secret_key is not None


class SECSettings(BaseSettings):
    """SEC EDGAR API configuration. SEC requires a User-Agent identifying the caller."""

    model_config = SettingsConfigDict(env_prefix="SEC_EDGAR_", extra="ignore")

    user_agent: str = "finsight your-email@example.com"


class AuthSettings(BaseSettings):
    """JWT authentication."""

    model_config = SettingsConfigDict(extra="ignore")

    jwt_secret_key: SecretStr = Field(
        default=SecretStr("generate-with-openssl-rand-hex-32"),
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expiration_minutes: int = Field(default=1440, ge=1, alias="JWT_EXPIRATION_MINUTES")


# ---------------------------------------------------------------------------
# Top-level Settings — composes all the groups above.
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Root settings container. Composes all sub-settings groups."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    api: APISettings = Field(default_factory=APISettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    sec: SECSettings = Field(default_factory=SECSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @property
    def is_production(self) -> bool:
        return self.app.env == AppEnv.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app.env == AppEnv.DEVELOPMENT

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        """Refuse to boot in production with insecure defaults."""
        if self.is_production:
            insecure_password = (
                self.postgres.password.get_secret_value() == "change-this-in-production"
            )
            insecure_jwt = (
                self.auth.jwt_secret_key.get_secret_value() == "generate-with-openssl-rand-hex-32"
            )

            problems: list[str] = []
            if insecure_password:
                problems.append("POSTGRES_PASSWORD is still the default placeholder")
            if insecure_jwt:
                problems.append("JWT_SECRET_KEY is still the default placeholder")
            if self.app.debug:
                problems.append("APP_DEBUG=true must not be set in production")

            if problems:
                raise ValueError(
                    "Refusing to start in production with insecure defaults: " + "; ".join(problems)
                )
        return self


# ---------------------------------------------------------------------------
# Public accessor. Cached so the Settings object is built exactly once.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Cached via lru_cache so that:
      - Validation runs only once per process
      - Tests can override by calling `get_settings.cache_clear()`
    """
    return Settings()
