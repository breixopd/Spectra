"""Edge-case tests for the webhook service: failed delivery, signature verification, deduplication."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webhooks.service import (
    MAX_RETRIES,
    RETRY_DELAYS,
    WebhookService,
    _deliver,
)


def _make_webhook(**overrides):
    wh = MagicMock()
    wh.id = overrides.get("id", "wh-1")
    wh.user_id = overrides.get("user_id", "user-1")
    wh.url = overrides.get("url", "https://hook.example.com/callback")
    wh.secret = overrides.get("secret")
    wh.events = overrides.get("events", ["mission.completed"])
    wh.is_active = overrides.get("is_active", True)
    wh.description = overrides.get("description")
    return wh


# ---------------------------------------------------------------------------
# Failed HTTP delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_logs_error_after_all_retries_exhausted():
    """After MAX_RETRIES failures the function returns without raising."""
    wh = _make_webhook()

    mock_client = AsyncMock()
    mock_client.post.side_effect = ConnectionError("refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Should NOT raise
            await _deliver(wh, "mission.completed", {"id": "m-1"})

    assert mock_client.post.await_count == MAX_RETRIES
    # Verify back-off delays were used (all except the last attempt)
    expected_sleeps = RETRY_DELAYS[: MAX_RETRIES - 1]
    actual_sleeps = [c.args[0] for c in mock_sleep.await_args_list]
    assert actual_sleeps == expected_sleeps


@pytest.mark.asyncio
async def test_deliver_http_4xx_still_retries():
    """4xx responses should still trigger retries (server treats < 400 as success)."""
    wh = _make_webhook()

    resp = MagicMock()
    resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.post.return_value = resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
            await _deliver(wh, "scan.error", {})

    assert mock_client.post.await_count == MAX_RETRIES


@pytest.mark.asyncio
async def test_deliver_succeeds_after_transient_failure():
    """Delivery succeeds on second attempt after one transient failure."""
    wh = _make_webhook()

    fail_resp = MagicMock()
    fail_resp.status_code = 503
    ok_resp = MagicMock()
    ok_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.side_effect = [fail_resp, ok_resp]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
            await _deliver(wh, "finding.new", {"id": "f-1"})

    assert mock_client.post.await_count == 2


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signature_matches_canonical_json():
    """HMAC signature is computed over canonical (compact, sorted) JSON with timestamp."""
    secret = "test-secret-key"
    wh = _make_webhook(secret=secret)
    event = "finding.new"
    payload = {"z": 2, "a": 1}
    fixed_ts = 1700000000

    body = {"event": event, "data": payload}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    sig_payload = f"{fixed_ts}.".encode() + raw
    expected_sig = "sha256=" + hmac.new(secret.encode(), sig_payload, hashlib.sha256).hexdigest()

    ok_resp = MagicMock()
    ok_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = ok_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhooks.service.time.time", return_value=float(fixed_ts)):
            await _deliver(wh, event, payload)

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["X-Spectra-Signature"] == expected_sig


@pytest.mark.asyncio
async def test_signature_absent_when_no_secret():
    """No signature header is sent when webhook has no secret."""
    wh = _make_webhook(secret=None)

    ok_resp = MagicMock()
    ok_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = ok_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        await _deliver(wh, "mission.completed", {})

    _, kwargs = mock_client.post.call_args
    assert "X-Spectra-Signature" not in kwargs["headers"]


@pytest.mark.asyncio
async def test_signature_uses_sha256():
    """Signature prefix is 'sha256=' and hex digest has correct length."""
    wh = _make_webhook(secret="k")

    ok_resp = MagicMock()
    ok_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post.return_value = ok_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
        await _deliver(wh, "mission.completed", {"x": 1})

    _, kwargs = mock_client.post.call_args
    sig = kwargs["headers"]["X-Spectra-Signature"]
    assert sig.startswith("sha256=")
    assert len(sig) == len("sha256=") + 64  # sha256 hex = 64 chars


# ---------------------------------------------------------------------------
# Duplicate webhook prevention (event-level dedup via fire)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_does_not_duplicate_delivery_to_same_hook():
    """A single hook subscribed to the event gets exactly one delivery."""
    session = AsyncMock()

    hook = _make_webhook(id="wh-dup", events=["mission.completed"])
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [hook]
    session.execute.return_value = mock_result

    svc = WebhookService(session)

    with patch("app.services.webhooks.service._deliver", new_callable=AsyncMock):
        with patch("spectra_common.tasks.create_safe_task") as mock_task:

            def _close_coro(coro, *, name=None):
                if asyncio.iscoroutine(coro):
                    coro.close()
                return MagicMock()

            mock_task.side_effect = _close_coro
            await svc.fire("mission.completed", {"id": "m-1"})

    assert mock_task.call_count == 1


@pytest.mark.asyncio
async def test_fire_skips_inactive_hooks():
    """fire() fetches only active hooks so inactive ones are never delivered."""
    session = AsyncMock()

    # The service queries WHERE is_active IS TRUE, so inactive hooks
    # should never appear in the result set.
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    svc = WebhookService(session)

    with patch("spectra_common.tasks.create_safe_task") as mock_task:
        await svc.fire("mission.completed", {"id": "m-1"})

    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_fire_multiple_hooks_each_get_one_delivery():
    """When two hooks both subscribe to the same event, each fires once."""
    session = AsyncMock()

    hook1 = _make_webhook(id="wh-1", events=["mission.completed"])
    hook2 = _make_webhook(id="wh-2", events=["mission.completed"])
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [hook1, hook2]
    session.execute.return_value = mock_result

    svc = WebhookService(session)

    with patch("app.services.webhooks.service._deliver", new_callable=AsyncMock):
        with patch("spectra_common.tasks.create_safe_task") as mock_task:

            def _close_coro(coro, *, name=None):
                if asyncio.iscoroutine(coro):
                    coro.close()
                return MagicMock()

            mock_task.side_effect = _close_coro
            await svc.fire("mission.completed", {"id": "m-1"})

    assert mock_task.call_count == 2
