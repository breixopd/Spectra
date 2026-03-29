from unittest.mock import AsyncMock, patch

import pytest

from app.core.bridge import EventWebSocketBridge
from app.core.events import EventType, events


@pytest.mark.asyncio
async def test_event_bridge_broadcasts_user_scoped_events():
    """User-scoped events route to broadcast_to_user_event when user_id is present."""
    bridge = EventWebSocketBridge()
    mock_ws_manager = AsyncMock()

    with patch("app.core.bridge.ws_manager", mock_ws_manager):
        bridge.start()

        try:
            test_data = {"test_key": "test_value", "user_id": "user-123"}
            await events.emit(EventType.MISSION_STARTED, "test_source", **test_data)

            mock_ws_manager.broadcast_to_user_event.assert_called()
            call_args = mock_ws_manager.broadcast_to_user_event.call_args
            assert call_args.kwargs["user_id"] == "user-123"
            assert call_args.kwargs["event_type"] == EventType.MISSION_STARTED.value
            assert call_args.kwargs["data"]["test_key"] == "test_value"
        finally:
            bridge.stop()


@pytest.mark.asyncio
async def test_event_bridge_suppresses_security_events():
    """Security-sensitive events must never be broadcast."""
    bridge = EventWebSocketBridge()
    mock_ws_manager = AsyncMock()

    with patch("app.core.bridge.ws_manager", mock_ws_manager):
        bridge.start()

        try:
            await events.emit(EventType.LOGIN_SUCCESS, "test_source", username="admin")
            await events.emit(EventType.LOGIN_FAILED, "test_source", username="admin")

            mock_ws_manager.broadcast_event.assert_not_called()
            mock_ws_manager.broadcast_to_user_event.assert_not_called()
        finally:
            bridge.stop()


@pytest.mark.asyncio
async def test_event_bridge_broadcasts_system_events_globally():
    """System/operational events are broadcast to all connections."""
    bridge = EventWebSocketBridge()
    mock_ws_manager = AsyncMock()

    with patch("app.core.bridge.ws_manager", mock_ws_manager):
        bridge.start()

        try:
            await events.emit(EventType.SERVICE_HEALTH_CHANGED, "test_source", service="db", status="healthy")

            mock_ws_manager.broadcast_event.assert_called()
            call_args = mock_ws_manager.broadcast_event.call_args
            assert call_args.kwargs["event_type"] == EventType.SERVICE_HEALTH_CHANGED.value
        finally:
            bridge.stop()
