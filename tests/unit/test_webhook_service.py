"""Tests for the webhook service: registration, firing, HMAC, retries, event filtering."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webhooks.service import (
    MAX_RETRIES,
    WebhookService,
    _deliver,
)


def _make_webhook(**overrides):
    """Create a mock Webhook object."""
    wh = MagicMock()
    wh.id = overrides.get("id", "wh-1")
    wh.user_id = overrides.get("user_id", "user-1")
    wh.url = overrides.get("url", "https://hook.example.com/callback")
    wh.secret = overrides.get("secret", None)
    wh.events = overrides.get("events", ["mission.completed"])
    wh.is_active = overrides.get("is_active", True)
    wh.description = overrides.get("description", None)
    return wh


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_webhook_success():
    session = AsyncMock()
    session.add = MagicMock()
    svc = WebhookService(session)

    with patch("app.services.webhooks.service.Webhook") as MockWH:
        instance = MagicMock()
        MockWH.return_value = instance
        await svc.register(
            user_id="u1",
            url="https://example.com/hook",
            events=["mission.completed"],
            secret="s3cret",
        )

    session.add.assert_called_once_with(instance)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(instance)


@pytest.mark.asyncio
async def test_register_webhook_rejects_invalid_events():
    session = AsyncMock()
    svc = WebhookService(session)
    with pytest.raises(ValueError, match="Unsupported webhook events"):
        await svc.register(
            user_id="u1",
            url="https://example.com/hook",
            events=["invalid.event"],
        )


# ---------------------------------------------------------------------------
# HMAC signature generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_includes_hmac_signature():
    """When webhook has a secret, X-Spectra-Signature header is set."""
    wh = _make_webhook(secret="mysecret")
    payload = {"key": "value"}
    event = "mission.completed"

    body = {"event": event, "data": payload}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    expected_sig = "sha256=" + hmac.new(
        b"mysecret", raw, hashlib.sha256
    ).hexdigest()

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        await _deliver(wh, event, payload)

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["X-Spectra-Signature"] == expected_sig


@pytest.mark.asyncio
async def test_deliver_no_signature_without_secret():
    """When webhook has no secret, no signature header is sent."""
    wh = _make_webhook(secret=None)

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        await _deliver(wh, "finding.new", {"f": 1})

    _, kwargs = mock_client.post.call_args
    assert "X-Spectra-Signature" not in kwargs["headers"]


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_retries_on_server_error():
    """_deliver retries up to MAX_RETRIES on HTTP 500."""
    wh = _make_webhook()

    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
            await _deliver(wh, "scan.error", {})

    assert mock_client.post.await_count == MAX_RETRIES


@pytest.mark.asyncio
async def test_deliver_retries_on_exception():
    """_deliver retries on network exceptions."""
    wh = _make_webhook()

    mock_client = AsyncMock()
    mock_client.post.side_effect = ConnectionError("network down")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
            await _deliver(wh, "scan.error", {})

    assert mock_client.post.await_count == MAX_RETRIES


@pytest.mark.asyncio
async def test_deliver_succeeds_on_first_try():
    """_deliver makes exactly one call on HTTP 200."""
    wh = _make_webhook()

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        await _deliver(wh, "mission.completed", {"status": "done"})

    assert mock_client.post.await_count == 1


# ---------------------------------------------------------------------------
# Event filtering (fire method)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_only_delivers_to_matching_hooks():
    """fire() only delivers to webhooks subscribed to the event."""
    session = AsyncMock()

    subscribed = _make_webhook(id="wh-1", events=["mission.completed"])
    not_subscribed = _make_webhook(id="wh-2", events=["scan.error"])

    # Setup session.execute to return both hooks
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [subscribed, not_subscribed]
    session.execute.return_value = mock_result

    svc = WebhookService(session)

    with patch("app.services.webhooks.service._deliver", new_callable=AsyncMock):
        with patch("app.services.webhooks.service.asyncio.create_task") as mock_task:
            # Make create_task call the coroutine arg tracking
            mock_task.side_effect = lambda coro: coro  # capture

            await svc.fire("mission.completed", {"id": "m-1"})

    # create_task called once (only for subscribed hook)
    assert mock_task.call_count == 1


@pytest.mark.asyncio
async def test_fire_no_delivery_when_no_matching_hooks():
    """fire() does nothing when no hooks subscribe to the event."""
    session = AsyncMock()

    hook = _make_webhook(events=["scan.error"])
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [hook]
    session.execute.return_value = mock_result

    svc = WebhookService(session)

    with patch("app.services.webhooks.service.asyncio.create_task") as mock_task:
        await svc.fire("finding.new", {"id": "f-1"})

    mock_task.assert_not_called()
