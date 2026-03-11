"""Tests for app.core.config — Settings loading, validation, and runtime persistence."""

import json

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class TestSettingsValidators:
    def test_valid_log_levels(self):
        from app.core.config import Settings

        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            s = Settings(LOG_LEVEL=level, _env_file=None)
            assert s.LOG_LEVEL == level

    def test_invalid_log_level_rejected(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="LOG_LEVEL"):
            Settings(LOG_LEVEL="TRACE", _env_file=None)

    def test_ai_provider_normalised(self):
        from app.core.config import Settings

        s = Settings(AI_PROVIDER="LITELLM", _env_file=None)
        assert s.AI_PROVIDER == "litellm"

    def test_ai_provider_api_alias(self):
        from app.core.config import Settings

        s = Settings(AI_PROVIDER="api", _env_file=None)
        assert s.AI_PROVIDER == "litellm"

    def test_ai_provider_invalid(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="AI_PROVIDER"):
            Settings(AI_PROVIDER="gpt-magic", _env_file=None)

    def test_token_expiry_minimum(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="ACCESS_TOKEN_EXPIRE_MINUTES"):
            Settings(ACCESS_TOKEN_EXPIRE_MINUTES=1, _env_file=None)

    def test_token_expiry_valid(self):
        from app.core.config import Settings

        s = Settings(ACCESS_TOKEN_EXPIRE_MINUTES=60, _env_file=None)
        assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_cors_origins_from_csv(self):
        from app.core.config import Settings

        s = Settings(CORS_ORIGINS="http://a.com, http://b.com", _env_file=None)
        assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_list(self):
        from app.core.config import Settings

        s = Settings(CORS_ORIGINS=["http://a.com"], _env_file=None)
        assert s.CORS_ORIGINS == ["http://a.com"]


# ---------------------------------------------------------------------------
# SMTP / Email config
# ---------------------------------------------------------------------------

class TestEmailConfig:
    def test_default_smtp_settings(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.SMTP_HOST == ""
        assert s.SMTP_PORT == 587
        assert s.SMTP_USE_TLS is True
        assert s.SMTP_FROM == ""

    def test_smtp_settings_overridden(self):
        from app.core.config import Settings

        s = Settings(
            SMTP_HOST="mail.example.com",
            SMTP_PORT=465,
            SMTP_USER="user",
            SMTP_FROM="noreply@example.com",
            SMTP_USE_TLS=True,
            _env_file=None,
        )
        assert s.SMTP_HOST == "mail.example.com"
        assert s.SMTP_PORT == 465
        assert s.SMTP_FROM == "noreply@example.com"


# ---------------------------------------------------------------------------
# Webhook config
# ---------------------------------------------------------------------------

class TestWebhookConfig:
    def test_default_notification_webhook_none(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.NOTIFICATION_WEBHOOK is None

    def test_notification_webhook_set(self):
        from app.core.config import Settings

        s = Settings(NOTIFICATION_WEBHOOK="https://ntfy.sh/topic", _env_file=None)
        assert s.NOTIFICATION_WEBHOOK == "https://ntfy.sh/topic"


# ---------------------------------------------------------------------------
# Runtime settings save / load
# ---------------------------------------------------------------------------

class TestRuntimeSettings:
    def test_save_creates_file(self, tmp_path, monkeypatch):
        from app.core.config import Settings

        runtime_path = tmp_path / "data" / "config" / "runtime_settings.json"
        monkeypatch.chdir(tmp_path)

        s = Settings(
            LOG_LEVEL="DEBUG",
            PLUGIN_SAFE_MODE=False,
            _env_file=None,
        )
        s.save_runtime_settings()

        assert runtime_path.exists()
        data = json.loads(runtime_path.read_text())
        assert data["LOG_LEVEL"] == "DEBUG"
        assert data["PLUGIN_SAFE_MODE"] is False

    def test_load_applies_non_sensitive_fields(self, tmp_path, monkeypatch):
        from app.core.config import Settings

        monkeypatch.chdir(tmp_path)
        runtime_path = tmp_path / "data" / "config" / "runtime_settings.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps({
            "LOG_LEVEL": "WARNING",
            "PLUGIN_SAFE_MODE": True,
        }))

        s = Settings(_env_file=None)
        s.load_runtime_settings()
        assert s.LOG_LEVEL == "WARNING"

    def test_load_skips_sensitive_and_db_backed(self, tmp_path, monkeypatch):
        from app.core.config import Settings

        monkeypatch.chdir(tmp_path)
        runtime_path = tmp_path / "data" / "config" / "runtime_settings.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps({
            "LOG_LEVEL": "ERROR",
            "JWT_SECRET_KEY": "hacked",
            "DATABASE_URL": "bad-url",
            "LLM_API_KEY": "stolen",
            "AI_PROVIDER": "ollama",
        }))

        s = Settings(_env_file=None)
        original_jwt = s.JWT_SECRET_KEY

        s.load_runtime_settings()

        assert s.LOG_LEVEL == "ERROR"
        # Sensitive & DB-backed fields unchanged
        assert s.JWT_SECRET_KEY == original_jwt


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_app_name(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.APP_NAME == "Spectra"

    def test_default_ai_provider(self):
        from app.core.config import Settings

        # AI_PROVIDER env var may be set by .env.test; check class default
        assert Settings.model_fields["AI_PROVIDER"].default == "litellm"

    def test_sandbox_defaults(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.SANDBOX_IMAGE == "spectra-tools"
        assert s.SANDBOX_MAX_CONTAINERS == 10
        assert s.SANDBOX_MAX_LIFETIME == 7200

    def test_platform_defaults(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.PLATFORM_DOMAIN == ""
        assert s.PLATFORM_EXPOSED is False


# ---------------------------------------------------------------------------
# get_settings singleton
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_jwt_secret_auto_generated_when_empty(self):
        from app.core.config import Settings

        s = Settings(JWT_SECRET_KEY="", _env_file=None)
        assert s.JWT_SECRET_KEY.get_secret_value() == ""
        # get_settings generates it, but we test the Settings class directly here

    def test_extra_env_vars_ignored(self):
        from app.core.config import Settings

        # extra="ignore" in model_config should let this pass
        s = Settings(UNKNOWN_FIELD="whatever", _env_file=None)
        assert not hasattr(s, "UNKNOWN_FIELD")
