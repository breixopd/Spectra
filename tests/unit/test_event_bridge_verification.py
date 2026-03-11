from unittest.mock import AsyncMock, patch

import pytest

from app.core.bridge import EventWebSocketBridge
from app.core.events import EventType, events


@pytest.mark.asyncio
async def test_event_bridge_broadcasts_events():
    # Setup
    bridge = EventWebSocketBridge()
    mock_ws_manager = AsyncMock()

    # Patch the ws_manager imported in app.core.bridge
    with patch("app.core.bridge.ws_manager", mock_ws_manager):
        bridge.start()

        try:
            # Action
            test_data = {"test_key": "test_value"}
            # Emit an event
            await events.emit(EventType.MISSION_STARTED, "test_source", **test_data)

            # Assert
            mock_ws_manager.broadcast_event.assert_called()

            # Check the last call
            call_args = mock_ws_manager.broadcast_event.call_args
            assert call_args.kwargs["event_type"] == EventType.MISSION_STARTED.value
            assert call_args.kwargs["data"]["test_key"] == "test_value"

        finally:
            bridge.stop()
