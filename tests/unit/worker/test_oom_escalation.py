"""Tests for OOM-based automatic resource tier escalation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTierEscalationPath:
    """TIER_ESCALATION_PATH defines correct upgrade chain."""

    def test_light_escalates_to_medium(self):
        from app.services.tools.sandbox.escalation import next_tier

        assert next_tier("light") == "medium"

    def test_medium_escalates_to_heavy(self):
        from app.services.tools.sandbox.escalation import next_tier

        assert next_tier("medium") == "heavy"

    def test_heavy_escalates_to_extreme(self):
        from app.services.tools.sandbox.escalation import next_tier

        assert next_tier("heavy") == "extreme"

    def test_extreme_has_no_escalation(self):
        from app.services.tools.sandbox.escalation import next_tier

        assert next_tier("extreme") is None

    def test_unknown_tier_has_no_escalation(self):
        from app.services.tools.sandbox.escalation import next_tier

        assert next_tier("nonexistent") is None


class TestAttemptOomEscalation:
    """attempt_oom_escalation unit tests."""

    @pytest.mark.asyncio
    async def test_disabled_returns_false(self):
        from app.services.tools.sandbox.escalation import attempt_oom_escalation

        with patch("app.services.tools.sandbox.escalation.get_settings") as mock:
            mock.return_value = MagicMock(SANDBOX_OOM_ESCALATION_ENABLED=False)
            success, msg = await attempt_oom_escalation("mission-123")
            assert success is False
            assert "disabled" in msg.lower()

    @pytest.mark.asyncio
    async def test_already_escalated_returns_false(self):
        from app.services.tools.sandbox.escalation import attempt_oom_escalation

        mock_sandbox = MagicMock(
            id="sb1",
            mission_id="m1",
            escalated=True,
            resource_tier="heavy",
            user_id=None,
        )
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sandbox
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.services.tools.sandbox.escalation.get_settings") as mock_settings,
            patch("app.services.tools.sandbox.escalation.async_session_maker", return_value=mock_session),
        ):
            mock_settings.return_value = MagicMock(SANDBOX_OOM_ESCALATION_ENABLED=True)
            success, msg = await attempt_oom_escalation("m1")
            assert success is False
            assert "already escalated" in msg.lower()

    @pytest.mark.asyncio
    async def test_extreme_tier_cannot_escalate(self):
        from app.services.tools.sandbox.escalation import attempt_oom_escalation

        mock_sandbox = MagicMock(
            id="sb1",
            mission_id="m1",
            escalated=False,
            resource_tier="extreme",
            user_id=None,
        )
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sandbox
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.services.tools.sandbox.escalation.get_settings") as mock_settings,
            patch("app.services.tools.sandbox.escalation.async_session_maker", return_value=mock_session),
        ):
            mock_settings.return_value = MagicMock(SANDBOX_OOM_ESCALATION_ENABLED=True)
            success, msg = await attempt_oom_escalation("m1")
            assert success is False
            assert "maximum tier" in msg.lower()


class TestOomConfig:
    """OOM escalation config setting."""

    def test_oom_escalation_enabled_default(self):
        from pydantic import SecretStr

        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"))
        assert s.SANDBOX_OOM_ESCALATION_ENABLED is True

    def test_escalated_column_on_sandbox(self):
        from app.models.infrastructure import Sandbox

        assert hasattr(Sandbox, "escalated")
