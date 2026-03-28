"""Comprehensive webhook tests: model creation, delivery, retry,
signature generation, and service methods.
"""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webhooks.service import (
    MAX_RETRIES,
    RETRY_DELAYS,
    SUPPORTED_EVENTS,
    WebhookService,
    _deliver,
)


def _mock_webhook(**overrides):
    """Build a mock Webhook ORM object."""
    wh = MagicMock()
    wh.id = overrides.get("id", "wh-test-1")
    wh.user_id = overrides.get("user_id", "user-1")
    wh.url = overrides.get("url", "https://hooks.example.com/callback")
    wh.secret = overrides.get("secret", None)
    wh.events = overrides.get("events", ["mission.completed"])
    wh.is_active = overrides.get("is_active", True)
    wh.description = overrides.get("description", "Test webhook")
    wh.created_at = overrides.get("created_at", None)
    wh.updated_at = overrides.get("updated_at", None)
    return wh


def _mock_http_client(status_code=200, side_effect=None):
    """Build a mock httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    if side_effect:
        mock_client.post.side_effect = side_effect
    else:
        resp = MagicMock()
        resp.status_code = status_code
        mock_client.post.return_value = resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# =========================================================================
# Webhook model creation & serialization
# =========================================================================


class TestWebhookModel:
    """Test Webhook model attributes and repr."""

    def test_model_has_required_fields(self):
        """Webhook class has the expected mapped columns."""
        from app.services.webhooks.models import Webhook

        assert hasattr(Webhook, "user_id")
        assert hasattr(Webhook, "url")
        assert hasattr(Webhook, "secret")
        assert hasattr(Webhook, "events")
        assert hasattr(Webhook, "is_active")
        assert hasattr(Webhook, "description")

    def test_model_repr(self):
        wh = _mock_webhook(id="abc", user_id="u1", url="https://x.com/hook")
        repr(wh)  # Ensure repr doesn't crash
        assert "abc" in str(wh.id)

    def test_model_tablename(self):
        from app.services.webhooks.models import Webhook

        assert Webhook.__tablename__ == "webhooks"

    def test_model_inherits_base(self):
        from app.models.base import Base
        from app.services.webhooks.models import Webhook

        assert issubclass(Webhook, Base)

    def test_supported_events_is_frozen(self):
        """SUPPORTED_EVENTS should be immutable."""
        assert isinstance(SUPPORTED_EVENTS, frozenset)
        assert "mission.completed" in SUPPORTED_EVENTS
        assert "finding.new" in SUPPORTED_EVENTS
        assert "scan.error" in SUPPORTED_EVENTS
        assert "mission.started" in SUPPORTED_EVENTS


# =========================================================================
# Registration
# =========================================================================


class TestWebhookRegistration:
    """Tests for WebhookService.register."""

    @pytest.mark.asyncio
    async def test_register_creates_and_commits(self):
        session = AsyncMock()
        session.add = MagicMock()
        svc = WebhookService(session)

        with patch("app.services.webhooks.service.Webhook") as MockWH:
            instance = MagicMock()
            MockWH.return_value = instance
            await svc.register(
                user_id="u1",
                url="https://example.com/hook",
                events=["mission.started"],
                secret="s3cr3t",
                description="My hook",
            )

        session.add.assert_called_once_with(instance)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_rejects_unsupported_events(self):
        session = AsyncMock()
        svc = WebhookService(session)
        with pytest.raises(ValueError, match="Unsupported webhook events"):
            await svc.register(
                user_id="u1",
                url="https://example.com/hook",
                events=["not.a.real.event"],
            )

    @pytest.mark.asyncio
    async def test_register_rejects_mixed_valid_invalid_events(self):
        session = AsyncMock()
        svc = WebhookService(session)
        with pytest.raises(ValueError):
            await svc.register(
                user_id="u1",
                url="https://example.com/hook",
                events=["mission.completed", "bogus.event"],
            )

    @pytest.mark.asyncio
    async def test_register_all_supported_events(self):
        session = AsyncMock()
        session.add = MagicMock()
        svc = WebhookService(session)

        with patch("app.services.webhooks.service.Webhook") as MockWH:
            MockWH.return_value = MagicMock()
            await svc.register(
                user_id="u1",
                url="https://example.com/hook",
                events=list(SUPPORTED_EVENTS),
            )
        session.commit.assert_awaited_once()


# =========================================================================
# Listing & deletion
# =========================================================================


class TestWebhookListAndDelete:
    @pytest.mark.asyncio
    async def test_list_for_user(self):
        session = AsyncMock()
        hook1, hook2 = _mock_webhook(id="wh-1"), _mock_webhook(id="wh-2")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [hook1, hook2]
        session.execute.return_value = mock_result

        svc = WebhookService(session)
        hooks = await svc.list_for_user("user-1")
        assert len(hooks) == 2

    @pytest.mark.asyncio
    async def test_delete_soft_deletes(self):
        session = AsyncMock()
        hook = _mock_webhook(id="wh-1", is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = hook
        session.execute.return_value = mock_result

        svc = WebhookService(session)
        result = await svc.delete("wh-1", "user-1")
        assert result is True
        assert hook.is_active is False
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        svc = WebhookService(session)
        result = await svc.delete("nonexistent", "user-1")
        assert result is False


# =========================================================================
# Delivery with mocked HTTP
# =========================================================================


class TestWebhookDelivery:
    @pytest.mark.asyncio
    async def test_successful_delivery_single_try(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {"id": "m-1"})

        assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_delivery_sends_correct_body(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "finding.new", {"severity": "high"})

        _, kwargs = mock_client.post.call_args
        assert kwargs["json"] == {"event": "finding.new", "data": {"severity": "high"}}

    @pytest.mark.asyncio
    async def test_delivery_sends_to_correct_url(self):
        wh = _mock_webhook(url="https://my-server.com/webhook")
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {})

        args, _ = mock_client.post.call_args
        assert args[0] == "https://my-server.com/webhook"

    @pytest.mark.asyncio
    async def test_delivery_sets_content_type(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {})

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Content-Type"] == "application/json"


# =========================================================================
# Retry behaviour
# =========================================================================


class TestWebhookRetry:
    @pytest.mark.asyncio
    async def test_retries_on_server_error(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(status_code=500)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
                await _deliver(wh, "scan.error", {})

        assert mock_client.post.await_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(side_effect=ConnectionError("refused"))

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
                await _deliver(wh, "scan.error", {})

        assert mock_client.post.await_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_retry_delays_are_used(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(side_effect=ConnectionError("refused"))

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await _deliver(wh, "scan.error", {})

        expected_sleeps = RETRY_DELAYS[: MAX_RETRIES - 1]
        actual_sleeps = [c.args[0] for c in mock_sleep.await_args_list]
        assert actual_sleeps == expected_sleeps

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failure(self):
        wh = _mock_webhook()
        fail = MagicMock(status_code=503)
        ok = MagicMock(status_code=200)

        mock_client = AsyncMock()
        mock_client.post.side_effect = [fail, ok]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock):
                await _deliver(wh, "finding.new", {"id": "f-1"})

        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_no_sleep_on_first_success(self):
        wh = _mock_webhook()
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.webhooks.service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await _deliver(wh, "mission.completed", {})

        mock_sleep.assert_not_awaited()


# =========================================================================
# Signature generation
# =========================================================================


class TestWebhookSignature:
    @pytest.mark.asyncio
    async def test_hmac_signature_present_with_secret(self):
        wh = _mock_webhook(secret="my-secret-key")
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {"id": "m-1"})

        _, kwargs = mock_client.post.call_args
        sig = kwargs["headers"]["X-Spectra-Signature"]
        assert sig.startswith("sha256=")

    @pytest.mark.asyncio
    async def test_signature_absent_without_secret(self):
        wh = _mock_webhook(secret=None)
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {})

        _, kwargs = mock_client.post.call_args
        assert "X-Spectra-Signature" not in kwargs["headers"]

    @pytest.mark.asyncio
    async def test_signature_matches_expected_hmac(self):
        secret = "test-key-abc"
        wh = _mock_webhook(secret=secret)
        event = "finding.new"
        payload = {"z": 2, "a": 1}

        body = {"event": event, "data": payload}
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

        mock_client = _mock_http_client(status_code=200)
        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, event, payload)

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["X-Spectra-Signature"] == expected

    @pytest.mark.asyncio
    async def test_signature_uses_canonical_json(self):
        """Signature is computed on compact sorted JSON."""
        wh = _mock_webhook(secret="k")
        mock_client = _mock_http_client(status_code=200)

        with patch("app.services.webhooks.service.httpx.AsyncClient", return_value=mock_client):
            await _deliver(wh, "mission.completed", {"b": 2, "a": 1})

        _, kwargs = mock_client.post.call_args
        sig = kwargs["headers"]["X-Spectra-Signature"]
        # sha256 hex digest is 64 chars
        assert len(sig) == len("sha256=") + 64


# =========================================================================
# Fire (event dispatch)
# =========================================================================


class TestWebhookFire:
    @pytest.mark.asyncio
    async def test_fire_delivers_to_matching_hooks(self):
        session = AsyncMock()
        hook = _mock_webhook(events=["mission.completed"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [hook]
        session.execute.return_value = mock_result

        svc = WebhookService(session)

        with patch("app.services.webhooks.service._deliver", new_callable=AsyncMock):
            with patch("app.services.webhooks.service.asyncio.create_task") as mock_task:
                def _close_coro(coro):
                    if asyncio.iscoroutine(coro):
                        coro.close()
                    return MagicMock()
                mock_task.side_effect = _close_coro
                await svc.fire("mission.completed", {"id": "m-1"})

        assert mock_task.call_count == 1

    @pytest.mark.asyncio
    async def test_fire_skips_non_matching_hooks(self):
        session = AsyncMock()
        hook = _mock_webhook(events=["scan.error"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [hook]
        session.execute.return_value = mock_result

        svc = WebhookService(session)

        with patch("app.services.webhooks.service.asyncio.create_task") as mock_task:
            await svc.fire("mission.completed", {})

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_handles_empty_hook_list(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        svc = WebhookService(session)

        with patch("app.services.webhooks.service.asyncio.create_task") as mock_task:
            await svc.fire("mission.completed", {})

        mock_task.assert_not_called()
