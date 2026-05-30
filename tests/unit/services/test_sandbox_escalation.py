from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_tools.sandbox.escalation import attempt_oom_escalation, next_tier


def test_next_tier():
    assert next_tier("light") == "medium"
    assert next_tier("medium") == "heavy"
    assert next_tier("heavy") == "extreme"
    assert next_tier("extreme") is None
    assert next_tier("unknown") is None


@pytest.mark.asyncio
async def test_attempt_oom_escalation_disabled():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = False

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        success, message = await attempt_oom_escalation("mission-1")

    assert success is False
    assert "disabled" in message


@pytest.mark.asyncio
async def test_attempt_oom_escalation_no_sandbox():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        with patch("spectra_tools.sandbox.escalation.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
            success, message = await attempt_oom_escalation("mission-1")

    assert success is False
    assert "No active sandbox" in message


@pytest.mark.asyncio
async def test_attempt_oom_escalation_already_escalated():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = True

    sandbox = MagicMock()
    sandbox.escalated = True
    sandbox.resource_tier = "medium"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sandbox

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        with patch("spectra_tools.sandbox.escalation.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
            success, message = await attempt_oom_escalation("mission-1")

    assert success is False
    assert "already escalated" in message


@pytest.mark.asyncio
async def test_attempt_oom_escalation_max_tier():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = True

    sandbox = MagicMock()
    sandbox.escalated = False
    sandbox.resource_tier = "extreme"
    sandbox.user_id = "user-1"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sandbox

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        with patch("spectra_tools.sandbox.escalation.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
            success, message = await attempt_oom_escalation("mission-1")

    assert success is False
    assert "maximum tier" in message


@pytest.mark.asyncio
async def test_attempt_oom_escalation_success():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = True

    sandbox = MagicMock()
    sandbox.id = "sb-1"
    sandbox.escalated = False
    sandbox.resource_tier = "medium"
    sandbox.user_id = "user-1"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sandbox

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_pool = AsyncMock()
    mock_pool.destroy = AsyncMock()
    mock_pool.create = AsyncMock()

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        with patch("spectra_tools.sandbox.escalation.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
            with patch("spectra_tools.sandbox.get_sandbox_pool", return_value=mock_pool):
                success, message = await attempt_oom_escalation("mission-1")

    assert success is True
    assert "heavy" in message
    mock_pool.destroy.assert_called_once_with("mission-1")
    mock_pool.create.assert_called_once_with("mission-1", resource_tier="heavy", user_id="user-1")


@pytest.mark.asyncio
async def test_attempt_oom_escalation_pool_unavailable():
    settings = MagicMock()
    settings.SANDBOX_OOM_ESCALATION_ENABLED = True

    sandbox = MagicMock()
    sandbox.id = "sb-1"
    sandbox.escalated = False
    sandbox.resource_tier = "medium"
    sandbox.user_id = "user-1"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sandbox

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_tools.sandbox.escalation.get_settings", return_value=settings):
        with patch("spectra_tools.sandbox.escalation.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
            with patch("spectra_tools.sandbox.get_sandbox_pool", return_value=None):
                success, message = await attempt_oom_escalation("mission-1")

    assert success is False
    assert "pool not available" in message
