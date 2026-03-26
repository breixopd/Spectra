"""Tests for app.core.config — Settings loading, validation, and runtime persistence."""


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

    def test_tensorzero_gateway_url_default_empty(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.TENSORZERO_GATEWAY_URL == ""

    def test_tensorzero_gateway_url_set(self):
        from app.core.config import Settings

        s = Settings(TENSORZERO_GATEWAY_URL="http://tensorzero:3000", _env_file=None)
        assert s.TENSORZERO_GATEWAY_URL == "http://tensorzero:3000"

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
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_app_name(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.APP_NAME == "Spectra"

    def test_default_tensorzero_gateway_url(self):
        from app.core.config import Settings

        # TENSORZERO_GATEWAY_URL defaults to empty string
        assert Settings.model_fields["TENSORZERO_GATEWAY_URL"].default == ""

    def test_sandbox_defaults(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.SANDBOX_IMAGE == "spectra-tools"


# ---------------------------------------------------------------------------
# SMTP_PORT validation
# ---------------------------------------------------------------------------


class TestSmtpPortValidation:
    def test_smtp_port_rejects_negative(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="SMTP_PORT"):
            Settings(SMTP_PORT=-1, _env_file=None)

    def test_smtp_port_rejects_zero(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="SMTP_PORT"):
            Settings(SMTP_PORT=0, _env_file=None)

    def test_smtp_port_rejects_over_65535(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="SMTP_PORT"):
            Settings(SMTP_PORT=70000, _env_file=None)

    def test_smtp_port_accepts_valid(self):
        from app.core.config import Settings

        s = Settings(SMTP_PORT=587, _env_file=None)
        assert s.SMTP_PORT == 587

    def test_smtp_port_accepts_boundary_low(self):
        from app.core.config import Settings

        s = Settings(SMTP_PORT=1, _env_file=None)
        assert s.SMTP_PORT == 1

    def test_smtp_port_accepts_boundary_high(self):
        from app.core.config import Settings

        s = Settings(SMTP_PORT=65535, _env_file=None)
        assert s.SMTP_PORT == 65535


# ---------------------------------------------------------------------------
# DATABASE_POOL_SIZE / DATABASE_MAX_OVERFLOW validation
# ---------------------------------------------------------------------------


class TestDatabasePoolValidation:
    def test_pool_size_rejects_zero(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="DATABASE_POOL_SIZE"):
            Settings(DATABASE_POOL_SIZE=0, _env_file=None)

    def test_pool_size_rejects_over_100(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="DATABASE_POOL_SIZE"):
            Settings(DATABASE_POOL_SIZE=101, _env_file=None)

    def test_pool_size_accepts_valid(self):
        from app.core.config import Settings

        s = Settings(DATABASE_POOL_SIZE=20, _env_file=None)
        assert s.DATABASE_POOL_SIZE == 20

    def test_pool_size_accepts_boundary_low(self):
        from app.core.config import Settings

        s = Settings(DATABASE_POOL_SIZE=1, _env_file=None)
        assert s.DATABASE_POOL_SIZE == 1

    def test_pool_size_accepts_boundary_high(self):
        from app.core.config import Settings

        s = Settings(DATABASE_POOL_SIZE=100, _env_file=None)
        assert s.DATABASE_POOL_SIZE == 100

    def test_max_overflow_rejects_over_100(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="DATABASE_MAX_OVERFLOW"):
            Settings(DATABASE_MAX_OVERFLOW=101, _env_file=None)

    def test_max_overflow_rejects_negative(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="DATABASE_MAX_OVERFLOW"):
            Settings(DATABASE_MAX_OVERFLOW=-1, _env_file=None)

    def test_max_overflow_accepts_zero(self):
        from app.core.config import Settings

        s = Settings(DATABASE_MAX_OVERFLOW=0, _env_file=None)
        assert s.DATABASE_MAX_OVERFLOW == 0

    def test_max_overflow_accepts_valid(self):
        from app.core.config import Settings

        s = Settings(DATABASE_MAX_OVERFLOW=10, _env_file=None)
        assert s.DATABASE_MAX_OVERFLOW == 10

    def test_defaults_pass_all_validators(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.DATABASE_POOL_SIZE == 20
        assert s.DATABASE_MAX_OVERFLOW == 10
        assert s.SMTP_PORT == 587
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
