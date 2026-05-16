"""Unit tests for finsight.config."""

from __future__ import annotations

import pytest

from finsight.config import (
    AppEnv,
    LogFormat,
    LogLevel,
    Settings,
    get_settings,
)


@pytest.mark.unit
class TestSettings:
    """Tests for the root Settings object and its sub-settings."""

    def test_settings_loads_without_error(self) -> None:
        """Settings should load even with no .env file present."""
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_app_settings_have_sensible_defaults(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.app.name == "finsight"
        assert settings.app.env in {AppEnv.DEVELOPMENT, AppEnv.STAGING, AppEnv.PRODUCTION}
        assert settings.app.log_level in {
            LogLevel.DEBUG,
            LogLevel.INFO,
            LogLevel.WARNING,
            LogLevel.ERROR,
        }
        assert settings.app.log_format in {LogFormat.CONSOLE, LogFormat.JSON}

    def test_api_port_is_valid(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert 1 <= settings.api.port <= 65535

    def test_cors_origins_is_list(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings.api.cors_origins, list)
        assert all(isinstance(origin, str) for origin in settings.api.cors_origins)

    def test_qdrant_url_is_set(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.qdrant.url.startswith(("http://", "https://"))

    def test_secrets_are_hidden_in_repr(self) -> None:
        """SecretStr should mask values in string representation."""
        get_settings.cache_clear()
        settings = get_settings()
        assert "change-this-in-production" not in repr(settings.postgres.password)
        assert "**********" in repr(settings.postgres.password)

    def test_get_settings_is_cached(self) -> None:
        """Repeated calls should return the same instance."""
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_langfuse_disabled_when_keys_missing(self) -> None:
        """The enabled property is False when both keys are unset."""
        get_settings.cache_clear()
        settings = get_settings()
        # With our .env having empty Langfuse keys, this should be False.
        assert settings.langfuse.enabled is False

    def test_is_development_helper(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.is_development is (settings.app.env == AppEnv.DEVELOPMENT)
        assert settings.is_production is (settings.app.env == AppEnv.PRODUCTION)


@pytest.mark.unit
class TestEnums:
    """Tests for the enum classes used in config."""

    def test_app_env_values(self) -> None:
        assert AppEnv.DEVELOPMENT == "development"
        assert AppEnv.STAGING == "staging"
        assert AppEnv.PRODUCTION == "production"

    def test_log_level_values(self) -> None:
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"

    def test_log_format_values(self) -> None:
        assert LogFormat.CONSOLE == "console"
        assert LogFormat.JSON == "json"
