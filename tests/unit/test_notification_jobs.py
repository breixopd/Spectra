"""Tests for notification worker tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- send_webhook_notification ---


@pytest.mark.asyncio
async def test_send_webhook_makes_http_post():
    from app.worker.notification_jobs import send_webhook_notification

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.notifications._is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "test"}, "https://hooks.example.com/test")

    assert result is True
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_webhook_handles_http_error_gracefully():
    from app.worker.notification_jobs import send_webhook_notification

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.notifications._is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "fail"}, "https://hooks.example.com/fail")

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_handles_network_exception():
    from app.worker.notification_jobs import send_webhook_notification

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.notifications._is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await send_webhook_notification({"event": "err"}, "https://hooks.example.com/err")

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_blocks_unsafe_url():
    from app.worker.notification_jobs import send_webhook_notification

    with patch("app.services.notifications._is_safe_url", return_value=False):
        result = await send_webhook_notification({"event": "bad"}, "http://169.254.169.254/metadata")

    assert result is False


# --- send_mission_completion_notification ---


@pytest.mark.asyncio
async def test_send_mission_completion_notification_finds_and_notifies():
    from app.models.finding import Finding
    from app.worker.notification_jobs import send_mission_completion_notification

    mock_mission = MagicMock()
    mock_mission.id = "mission-1"
    mock_mission.target = "10.0.0.1"

    mock_finding = MagicMock()
    mock_finding.severity = "critical"

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = mock_mission

    findings_result = MagicMock()
    findings_result.scalars.return_value.all.return_value = [mock_finding]

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[mission_result, findings_result])

    # Finding model lacks mission_id; patch it for this worker code path
    with (
        patch("app.services.notifications.notify_mission_completed", new_callable=AsyncMock) as mock_notify,
        patch.object(Finding, "mission_id", create=True, new_callable=lambda: MagicMock()),
    ):
        await send_mission_completion_notification("mission-1", session)

    mock_notify.assert_awaited_once_with("10.0.0.1", 1, 1)


@pytest.mark.asyncio
async def test_send_mission_completion_notification_missing_mission():
    from app.worker.notification_jobs import send_mission_completion_notification

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    # Should not raise
    await send_mission_completion_notification("nonexistent", session)


# --- send_critical_finding_alert ---


@pytest.mark.asyncio
async def test_send_critical_finding_alert_sends_for_critical():
    from app.worker.notification_jobs import send_critical_finding_alert

    mock_finding = MagicMock()
    mock_finding.severity = "critical"
    mock_finding.title = "SQL Injection"
    mock_finding.description = "Unparameterized query"

    finding_result = MagicMock()
    finding_result.scalar_one_or_none.return_value = mock_finding

    session = AsyncMock()
    session.execute = AsyncMock(return_value=finding_result)

    with patch("app.services.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        await send_critical_finding_alert("finding-1", session)

    mock_send.assert_awaited_once()
    call_kwargs = mock_send.call_args
    assert "CRITICAL" in call_kwargs.kwargs.get("title", call_kwargs.args[0] if call_kwargs.args else "")


@pytest.mark.asyncio
async def test_send_critical_finding_alert_skips_low_severity():
    from app.worker.notification_jobs import send_critical_finding_alert

    mock_finding = MagicMock()
    mock_finding.severity = "low"
    mock_finding.title = "Info Disclosure"
    mock_finding.description = "Minor issue"

    finding_result = MagicMock()
    finding_result.scalar_one_or_none.return_value = mock_finding

    session = AsyncMock()
    session.execute = AsyncMock(return_value=finding_result)

    with patch("app.services.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        await send_critical_finding_alert("finding-2", session)

    mock_send.assert_not_awaited()
