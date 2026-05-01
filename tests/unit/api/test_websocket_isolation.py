"""
Tests for WebSocket event isolation across users.

Verifies that the EventWebSocketBridge routes user-scoped events only to
their owning user's connections and never bleeds events between users.
"""

from unittest.mock import AsyncMock, patch

import pytest

from spectra_platform.infrastructure.events import EventType, events
from spectra_platform.mission.core.bridge import _USER_SCOPED_EVENTS, EventWebSocketBridge


class TestWebSocketEventIsolation:
    """User-scoped events reach only the owning user's WebSocket channel."""

    @pytest.mark.asyncio
    async def test_user_a_event_routes_to_user_a_only(self):
        """A mission event for user-a is dispatched with user_id='user-a'."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                await events.emit(
                    EventType.MISSION_STARTED,
                    "test",
                    user_id="user-a",
                    mission_id="m-1",
                )
            finally:
                bridge.stop()

        mock_ws.broadcast_to_user_event.assert_called_once()
        kwargs = mock_ws.broadcast_to_user_event.call_args.kwargs
        assert kwargs["user_id"] == "user-a"

    @pytest.mark.asyncio
    async def test_user_b_does_not_receive_user_a_event(self):
        """broadcast_to_user_event is never called with user-b for a user-a event."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                await events.emit(
                    EventType.MISSION_COMPLETED,
                    "test",
                    user_id="user-a",
                )
            finally:
                bridge.stop()

        for call in mock_ws.broadcast_to_user_event.call_args_list:
            assert call.kwargs.get("user_id") != "user-b", "user-b should not receive an event destined for user-a"

    @pytest.mark.asyncio
    async def test_two_user_events_route_to_separate_channels(self):
        """Events for different users are sent to their respective channels."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                await events.emit(EventType.MISSION_STARTED, "test", user_id="user-a")
                await events.emit(EventType.MISSION_COMPLETED, "test", user_id="user-b")
            finally:
                bridge.stop()

        assert mock_ws.broadcast_to_user_event.call_count == 2
        routed_users = {call.kwargs["user_id"] for call in mock_ws.broadcast_to_user_event.call_args_list}
        assert routed_users == {"user-a", "user-b"}
        # Neither event should have triggered a global broadcast
        mock_ws.broadcast_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_scoped_event_without_user_id_is_dropped(self):
        """A user-scoped event missing user_id is dropped silently — not broadcast."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                # Emit a user-scoped event type without user_id
                await events.emit(
                    EventType.MISSION_STARTED,
                    "test",
                    mission_id="m-orphan",
                )
            finally:
                bridge.stop()

        mock_ws.broadcast_to_user_event.assert_not_called()
        mock_ws.broadcast_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_event_broadcasts_globally_not_per_user(self):
        """Non-user-scoped (system) events are broadcast globally."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                await events.emit(
                    EventType.SERVICE_HEALTH_CHANGED,
                    "test",
                    service="db",
                    status="healthy",
                )
            finally:
                bridge.stop()

        mock_ws.broadcast_event.assert_called()
        mock_ws.broadcast_to_user_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_login_success_event_is_suppressed(self):
        """LOGIN_SUCCESS must never be sent to any client."""
        bridge = EventWebSocketBridge()
        mock_ws = AsyncMock()

        with patch("spectra_platform.mission.core.bridge.ws_manager", mock_ws):
            bridge.start()
            try:
                await events.emit(EventType.LOGIN_SUCCESS, "test", username="alice")
            finally:
                bridge.stop()

        mock_ws.broadcast_event.assert_not_called()
        mock_ws.broadcast_to_user_event.assert_not_called()

    def test_user_scoped_event_types_are_defined(self):
        """_USER_SCOPED_EVENTS must be non-empty — routing contract exists."""
        assert len(_USER_SCOPED_EVENTS) > 0
        # Mission events must definitely be user-scoped
        assert EventType.MISSION_STARTED in _USER_SCOPED_EVENTS
        assert EventType.MISSION_COMPLETED in _USER_SCOPED_EVENTS
