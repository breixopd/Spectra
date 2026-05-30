"""Tests for notification worker tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- send_webhook_notification ---


@pytest.mark.asyncio
async def test_send_webhook_makes_http_post():
    from spectra_worker.notification_jobs import send_webhook_notification

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("spectra_common.utils.url_validation.is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "test"}, "https://hooks.example.com/test")

    assert result is True
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_webhook_handles_http_error_gracefully():
    from spectra_worker.notification_jobs import send_webhook_notification

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("spectra_common.utils.url_validation.is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "fail"}, "https://hooks.example.com/fail")

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_handles_network_exception():
    from spectra_worker.notification_jobs import send_webhook_notification

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=ConnectionError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("spectra_common.utils.url_validation.is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "err"}, "https://hooks.example.com/err")

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_blocks_unsafe_url():
    from spectra_worker.notification_jobs import send_webhook_notification

    with patch("spectra_common.utils.url_validation.is_safe_url", return_value=False):
        result = await send_webhook_notification({"event": "bad"}, "http://169.254.169.254/metadata")

    assert result is False


# --- send_mission_completion_notification ---


@pytest.mark.asyncio
async def test_send_mission_completion_notification_finds_and_notifies():
    from spectra_worker.notification_jobs import send_mission_completion_notification

    mock_mission = MagicMock()
    mock_mission.id = "mission-1"
    mock_mission.target = "10.0.0.1"
    mock_mission.summary = {
        "findings": [
            {"title": "Test Finding", "severity": "critical", "description": "desc"},
        ]
    }

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = mock_mission

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    with patch("spectra_system.notifications.notify_mission_completed", new_callable=AsyncMock) as mock_notify:
        await send_mission_completion_notification("mission-1", session)

    mock_notify.assert_awaited_once_with("10.0.0.1", 1, 1)


@pytest.mark.asyncio
async def test_send_mission_completion_notification_normalizes_severity_counts():
    from spectra_worker.notification_jobs import send_mission_completion_notification

    mock_mission = MagicMock()
    mock_mission.id = "mission-2"
    mock_mission.target = "10.0.0.2"
    mock_mission.summary = {
        "findings": [
            {"title": "Critical Finding", "severity": "CRITICAL"},
            {"title": "Missing Severity", "severity": None},
            {"title": "Unknown Severity", "severity": "unexpected"},
        ]
    }

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = mock_mission

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    with patch("spectra_system.notifications.notify_mission_completed", new_callable=AsyncMock) as mock_notify:
        await send_mission_completion_notification("mission-2", session)

    mock_notify.assert_awaited_once_with("10.0.0.2", 3, 1)


@pytest.mark.asyncio
async def test_send_mission_completion_notification_missing_mission():
    from spectra_worker.notification_jobs import send_mission_completion_notification

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    # Should not raise
    await send_mission_completion_notification("nonexistent", session)


# --- send_critical_finding_alert ---


@pytest.mark.asyncio
async def test_send_critical_finding_alert_sends_for_critical():
    from spectra_worker.notification_jobs import send_critical_finding_alert

    mock_finding = MagicMock()
    mock_finding.severity = "critical"
    mock_finding.title = "SQL Injection"
    mock_finding.description = "Unparameterized query"

    finding_result = MagicMock()
    finding_result.scalar_one_or_none.return_value = mock_finding

    session = AsyncMock()
    session.execute = AsyncMock(return_value=finding_result)

    with patch("spectra_system.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        await send_critical_finding_alert("finding-1", session)

    mock_send.assert_awaited_once()
    call_kwargs = mock_send.call_args
    assert "CRITICAL" in call_kwargs.kwargs.get("title", call_kwargs.args[0] if call_kwargs.args else "")


@pytest.mark.asyncio
async def test_send_critical_finding_alert_skips_low_severity():
    from spectra_worker.notification_jobs import send_critical_finding_alert

    mock_finding = MagicMock()
    mock_finding.severity = "low"
    mock_finding.title = "Info Disclosure"
    mock_finding.description = "Minor issue"

    finding_result = MagicMock()
    finding_result.scalar_one_or_none.return_value = mock_finding

    session = AsyncMock()
    session.execute = AsyncMock(return_value=finding_result)

    with patch("spectra_system.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        await send_critical_finding_alert("finding-2", session)

    mock_send.assert_not_awaited()
