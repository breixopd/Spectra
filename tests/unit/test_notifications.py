"""Tests for notification system — SSRF protection, in-app delivery, and event wiring."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.events import Event, EventType
from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationService,
    _is_safe_url,
)


def _fake_addrinfo(ip: str):
    """Create a fake getaddrinfo result for a given IP."""
    return [(None, None, None, None, (ip, 0))]


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestIsSafeUrl:
    """Tests for _is_safe_url SSRF protection."""

    def test_rejects_localhost(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1")):
            assert _is_safe_url("http://localhost/hook") is False

    def test_rejects_127_0_0_1(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1")):
            assert _is_safe_url("http://127.0.0.1/hook") is False

    def test_rejects_10_x_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("10.0.0.5")):
            assert _is_safe_url("http://internal.corp/hook") is False

    def test_rejects_172_16_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("172.16.0.1")):
            assert _is_safe_url("http://internal.corp/hook") is False

    def test_rejects_192_168_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.1")):
            assert _is_safe_url("http://homerouter.local/hook") is False

    def test_rejects_link_local(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("169.254.1.1")):
            assert _is_safe_url("http://whatever/hook") is False

    def test_accepts_valid_external_url(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("1.2.3.4")):
            assert _is_safe_url("https://hooks.slack.com/webhook") is True

    def test_rejects_file_scheme(self):
        assert _is_safe_url("file:///etc/passwd") is False

    def test_rejects_ftp_scheme(self):
        assert _is_safe_url("ftp://evil.com/data") is False

    def test_rejects_empty_string(self):
        assert _is_safe_url("") is False

    def test_handles_malformed_url(self):
        assert _is_safe_url("not a url at all") is False

    def test_handles_dns_failure(self):
        import socket

        with patch("app.services.notifications.socket.getaddrinfo", side_effect=socket.gaierror("no dns")):
            assert _is_safe_url("http://does.not.exist.example/hook") is False

    def test_rejects_url_without_hostname(self):
        assert _is_safe_url("http:///path") is False


# ---------------------------------------------------------------------------
# NotificationService — in-app delivery
# ---------------------------------------------------------------------------


def _make_notification(
    *,
    user_id: str = "user-1",
    title: str = "Test",
    message: str = "hello",
    channel: NotificationChannel = NotificationChannel.IN_APP,
    priority: NotificationPriority = NotificationPriority.MEDIUM,
    event_type: str | None = None,
) -> Notification:
    return Notification(
        user_id=user_id,
        title=title,
        message=message,
        channel=channel,
        priority=priority,
        event_type=event_type,
    )


class TestNotificationServiceSend:
    @pytest.mark.asyncio
    async def test_send_in_app_stores_via_cache(self):
        svc = NotificationService()
        note = _make_notification()

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.set = AsyncMock()
            result = await svc.send(note)

        assert result is True
        mock_cache.set.assert_awaited_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "notifications"
        assert call_args[0][1].startswith("user-1:")

    @pytest.mark.asyncio
    async def test_send_webhook_delegates_to_send_notification(self):
        svc = NotificationService()
        note = _make_notification(channel=NotificationChannel.WEBHOOK)

        with patch(
            "app.services.notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            result = await svc.send(note)

        assert result is True
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_stores_serialized_json(self):
        svc = NotificationService()
        note = _make_notification(title="Important")

        stored_value = None

        async def _capture_set(ns, key, value, **kwargs):
            nonlocal stored_value
            stored_value = value

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.set = _capture_set
            await svc.send(note)

        assert stored_value is not None
        data = json.loads(stored_value)
        assert data["title"] == "Important"
        assert data["user_id"] == "user-1"
        assert data["read"] is False


class TestNotificationServiceRead:
    @pytest.mark.asyncio
    async def test_get_user_notifications_returns_sorted(self):
        svc = NotificationService()
        raw_rows = [
            json.dumps({"title": "Old", "created_at": "2025-01-01T00:00:00"}),
            json.dumps({"title": "New", "created_at": "2025-12-01T00:00:00"}),
        ]

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.scan_prefix = AsyncMock(return_value=raw_rows)
            result = await svc.get_user_notifications("user-1")

        assert len(result) == 2
        assert result[0]["title"] == "New"  # newest first

    @pytest.mark.asyncio
    async def test_get_user_notifications_respects_limit(self):
        svc = NotificationService()
        raw_rows = [json.dumps({"title": f"n{i}", "created_at": f"2025-01-{i + 1:02d}T00:00:00"}) for i in range(10)]

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.scan_prefix = AsyncMock(return_value=raw_rows)
            result = await svc.get_user_notifications("user-1", limit=3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_user_notifications_skips_invalid_json(self):
        svc = NotificationService()
        raw_rows = ["not-json", json.dumps({"title": "OK", "created_at": "2025-01-01T00:00:00"})]

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.scan_prefix = AsyncMock(return_value=raw_rows)
            result = await svc.get_user_notifications("user-1")

        assert len(result) == 1
        assert result[0]["title"] == "OK"

    @pytest.mark.asyncio
    async def test_get_unread_count(self):
        svc = NotificationService()
        raw_rows = [
            json.dumps({"title": "a", "read": False, "created_at": "2025-01-01T00:00:00"}),
            json.dumps({"title": "b", "read": True, "created_at": "2025-01-02T00:00:00"}),
            json.dumps({"title": "c", "read": False, "created_at": "2025-01-03T00:00:00"}),
        ]

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.scan_prefix = AsyncMock(return_value=raw_rows)
            count = await svc.get_unread_count("user-1")

        assert count == 2


class TestNotificationServiceMarkRead:
    @pytest.mark.asyncio
    async def test_mark_read_updates_cache(self):
        svc = NotificationService()
        note_data = json.dumps({"title": "t", "read": False})

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.get = AsyncMock(return_value=note_data)
            mock_cache.set = AsyncMock()
            result = await svc.mark_read("user-1", "note-1")

        assert result is True
        stored = json.loads(mock_cache.set.call_args[0][2])
        assert stored["read"] is True

    @pytest.mark.asyncio
    async def test_mark_read_returns_false_for_missing(self):
        svc = NotificationService()

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)
            result = await svc.mark_read("user-1", "does-not-exist")

        assert result is False


class TestNotificationServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_from_cache(self):
        svc = NotificationService()

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.get = AsyncMock(return_value='{"title":"x"}')
            mock_cache.delete = AsyncMock()
            result = await svc.delete("user-1", "note-1")

        assert result is True
        mock_cache.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing(self):
        svc = NotificationService()

        with patch("app.services.cache.CacheService") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)
            result = await svc.delete("user-1", "gone")

        assert result is False


# ---------------------------------------------------------------------------
# Event wiring
# ---------------------------------------------------------------------------


class TestNotificationEventHandlers:
    @pytest.mark.asyncio
    async def test_mission_completed_sends_notification(self):
        from app.services.notification_events import _on_mission_completed

        event = Event(
            type=EventType.MISSION_COMPLETED,
            data={"user_id": "u-1", "target": "10.0.0.1", "findings_count": 5},
        )

        with patch(
            "app.services.notification_events.notification_service.send",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            await _on_mission_completed(event)

        mock_send.assert_awaited_once()
        sent_note: Notification = mock_send.call_args[0][0]
        assert sent_note.user_id == "u-1"
        assert "10.0.0.1" in sent_note.message
        assert sent_note.event_type == EventType.MISSION_COMPLETED

    @pytest.mark.asyncio
    async def test_mission_completed_skips_when_no_user_id(self):
        from app.services.notification_events import _on_mission_completed

        event = Event(type=EventType.MISSION_COMPLETED, data={"target": "x"})

        with patch(
            "app.services.notification_events.notification_service.send",
            new_callable=AsyncMock,
        ) as mock_send:
            await _on_mission_completed(event)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mission_failed_sends_high_priority(self):
        from app.services.notification_events import _on_mission_failed

        event = Event(
            type=EventType.MISSION_FAILED,
            data={"user_id": "u-2", "target": "app.test", "reason": "timeout"},
        )

        with patch(
            "app.services.notification_events.notification_service.send",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            await _on_mission_failed(event)

        sent_note: Notification = mock_send.call_args[0][0]
        assert sent_note.priority == NotificationPriority.HIGH

    @pytest.mark.asyncio
    async def test_critical_finding_sends_critical_priority(self):
        from app.services.notification_events import _on_critical_finding

        event = Event(
            type=EventType.FINDING_DISCOVERED,
            data={"user_id": "u-3", "severity": "critical", "title": "RCE found"},
        )

        with patch(
            "app.services.notification_events.notification_service.send",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            await _on_critical_finding(event)

        sent_note: Notification = mock_send.call_args[0][0]
        assert sent_note.priority == NotificationPriority.CRITICAL

    @pytest.mark.asyncio
    async def test_non_critical_finding_ignored(self):
        from app.services.notification_events import _on_critical_finding

        event = Event(
            type=EventType.FINDING_DISCOVERED,
            data={"user_id": "u-3", "severity": "low", "title": "info leak"},
        )

        with patch(
            "app.services.notification_events.notification_service.send",
            new_callable=AsyncMock,
        ) as mock_send:
            await _on_critical_finding(event)

        mock_send.assert_not_awaited()

    def test_register_subscribes_handlers(self):
        from app.services.notification_events import register_notification_handlers

        with patch("app.services.notification_events.events") as mock_bus:
            register_notification_handlers()

        assert mock_bus.subscribe.call_count == 3
        subscribed_types = {call.args[0] for call in mock_bus.subscribe.call_args_list}
        assert EventType.MISSION_COMPLETED in subscribed_types
        assert EventType.MISSION_FAILED in subscribed_types
        assert EventType.FINDING_DISCOVERED in subscribed_types
