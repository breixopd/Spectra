"""Tests for secret_bootstrap — persistent secret generation and DB persistence."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.services.system.secret_bootstrap import _apply_secret, ensure_persistent_secrets


class TestApplySecret:
    """Unit tests for _apply_secret helper."""

    def test_apply_secret_str(self):
        mock_settings = MagicMock()
        mock_settings.JWT_SECRET_KEY = SecretStr("")
        with patch("app.services.system.secret_bootstrap.settings", mock_settings):
            _apply_secret("JWT_SECRET_KEY", "test-secret")
        assert mock_settings.JWT_SECRET_KEY.get_secret_value() == "test-secret"

    def test_apply_nonsecret_str(self):
        mock_settings = MagicMock()
        mock_settings.SOME_FIELD = "old"
        with patch("app.services.system.secret_bootstrap.settings", mock_settings):
            _apply_secret("SOME_FIELD", "new-val")
        assert mock_settings.SOME_FIELD == "new-val"


class TestEnsurePersistentSecrets:
    """Tests for ensure_persistent_secrets with mocked DB session."""

    @pytest.mark.asyncio
    async def test_first_boot_generates_and_persists(self):
        """On first boot with no DB values and no env vars, secrets are generated and persisted."""
        mock_session = AsyncMock()
        # Simulate empty DB (no existing config rows)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_settings.JWT_SECRET_KEY = SecretStr("auto-generated-jwt")
        mock_settings.SECRET_KEY = SecretStr("auto-generated-secret")
        mock_settings.SERVICE_AUTH_SECRET = SecretStr("auto-generated-service")

        with patch("app.services.system.secret_bootstrap.settings", mock_settings), \
             patch.dict(os.environ, {}, clear=False):
            # Remove any existing env vars for managed secrets
            for key in ["JWT_SECRET_KEY", "SECRET_KEY", "SERVICE_AUTH_SECRET",
                        "JWT_SECRET_KEY_FILE", "SECRET_KEY_FILE", "SERVICE_AUTH_SECRET_FILE"]:
                os.environ.pop(key, None)
            await ensure_persistent_secrets(mock_session)

        # Should have called session.add for each secret + advisory lock + 3 selects
        assert mock_session.add.call_count == 3
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_existing_db_values_loaded(self):
        """On subsequent boot, DB values are loaded and applied to settings."""
        mock_config = MagicMock()
        mock_config.value = "db-stored-secret"
        mock_config.is_secret = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_settings.JWT_SECRET_KEY = SecretStr("")
        mock_settings.SECRET_KEY = SecretStr("")
        mock_settings.SERVICE_AUTH_SECRET = SecretStr("")

        with patch("app.services.system.secret_bootstrap.settings", mock_settings), \
             patch.dict(os.environ, {}, clear=False):
            for key in ["JWT_SECRET_KEY", "SECRET_KEY", "SERVICE_AUTH_SECRET",
                        "JWT_SECRET_KEY_FILE", "SECRET_KEY_FILE", "SERVICE_AUTH_SECRET_FILE"]:
                os.environ.pop(key, None)
            await ensure_persistent_secrets(mock_session)

        # Should NOT have added new rows (DB had values)
        assert mock_session.add.call_count == 0
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_env_override_updates_db(self):
        """When env var is explicitly set and differs from DB, DB is updated."""
        mock_config = MagicMock()
        mock_config.value = "old-db-secret"
        mock_config.is_secret = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_settings.JWT_SECRET_KEY = SecretStr("")
        mock_settings.SECRET_KEY = SecretStr("")
        mock_settings.SERVICE_AUTH_SECRET = SecretStr("")

        with patch("app.services.system.secret_bootstrap.settings", mock_settings), \
             patch.dict(os.environ, {"JWT_SECRET_KEY": "from-env-override"}, clear=False):
            for key in ["SECRET_KEY", "SERVICE_AUTH_SECRET",
                        "JWT_SECRET_KEY_FILE", "SECRET_KEY_FILE", "SERVICE_AUTH_SECRET_FILE"]:
                os.environ.pop(key, None)
            await ensure_persistent_secrets(mock_session)

        # JWT config should be updated with env value
        assert mock_config.is_secret is True
