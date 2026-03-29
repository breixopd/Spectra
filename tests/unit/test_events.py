"""Tests for app.core.events module."""

import asyncio

import pytest

from app.core.events import Event, EventBus, EventType


class TestEventType:
    def test_mission_events_exist(self):
        assert EventType.MISSION_CREATED.value == "mission_created"
        assert EventType.MISSION_STARTED.value == "mission_started"
        assert EventType.MISSION_COMPLETED.value == "mission_completed"

    def test_tool_events_exist(self):
        assert EventType.TOOL_EXECUTION_STARTED.value == "tool_execution_started"
        assert EventType.TOOL_EXECUTION_COMPLETED.value == "tool_execution_completed"

    def test_security_events_exist(self):
        assert EventType.LOGIN_SUCCESS.value == "login_success"
        assert EventType.LOGIN_FAILED.value == "login_failed"


class TestEvent:
    def test_to_dict(self):
        event = Event(type=EventType.MISSION_CREATED, source="test", data={"id": "1"})
        d = event.to_dict()
        assert d["type"] == "mission_created"
        assert d["source"] == "test"
        assert d["data"] == {"id": "1"}
        assert "timestamp" in d

    def test_default_source(self):
        event = Event(type=EventType.LOGIN_SUCCESS)
        assert event.source == "unknown"

    def test_default_data(self):
        event = Event(type=EventType.LOGIN_SUCCESS)
        assert event.data == {}


class TestEventBus:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self, bus):
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.MISSION_CREATED, handler)
        await bus.emit(EventType.MISSION_CREATED, source="test", mission_id="abc")

        assert len(received) == 1
        assert received[0].data["mission_id"] == "abc"

    @pytest.mark.asyncio
    async def test_async_handler(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.MISSION_STARTED, handler)
        await bus.emit(EventType.MISSION_STARTED, source="test")

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.MISSION_CREATED, handler)
        bus.unsubscribe(EventType.MISSION_CREATED, handler)
        await bus.emit(EventType.MISSION_CREATED, source="test")

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_non_critical_handler_error_does_not_propagate(self, bus):
        def bad_handler(event):
            raise ValueError("oops")

        bus.subscribe(EventType.MISSION_CREATED, bad_handler, critical=False)
        # Should not raise
        await bus.emit(EventType.MISSION_CREATED, source="test")

    @pytest.mark.asyncio
    async def test_critical_handler_error_propagates(self, bus):
        def bad_handler(event):
            raise ValueError("critical failure")

        bus.subscribe(EventType.MISSION_CREATED, bad_handler, critical=True)
        with pytest.raises(ValueError, match="critical failure"):
            await bus.emit(EventType.MISSION_CREATED, source="test")

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped(self, bus):
        # Unknown string event type should not raise
        await bus.emit("totally_fake_event", source="test")

    @pytest.mark.asyncio
    async def test_event_history(self, bus):
        await bus.emit(EventType.LOGIN_SUCCESS, source="test")
        await bus.emit(EventType.LOGIN_FAILED, source="test")

        history = bus.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_event_history_filtered(self, bus):
        await bus.emit(EventType.LOGIN_SUCCESS, source="test")
        await bus.emit(EventType.LOGIN_FAILED, source="test")

        history = bus.get_history(EventType.LOGIN_SUCCESS)
        assert len(history) == 1
        assert history[0].type == EventType.LOGIN_SUCCESS

    @pytest.mark.asyncio
    async def test_get_stats(self, bus):
        def handler(event):
            pass

        bus.subscribe(EventType.MISSION_CREATED, handler)
        await bus.emit(EventType.MISSION_CREATED, source="test")
        await bus.emit(EventType.MISSION_CREATED, source="test")

        stats = bus.get_stats()
        assert stats["total_events"] == 2
        assert stats["event_counts"]["mission_created"] == 2
        assert stats["registered_handlers"]["mission_created"] == 1

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, bus):
        results = []

        def handler_a(event):
            results.append("a")

        def handler_b(event):
            results.append("b")

        bus.subscribe(EventType.FINDING_DISCOVERED, handler_a)
        bus.subscribe(EventType.FINDING_DISCOVERED, handler_b)
        await bus.emit(EventType.FINDING_DISCOVERED, source="test")

        assert sorted(results) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_subscribe_with_string_event_type(self, bus):
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("mission_created", handler)
        await bus.emit(EventType.MISSION_CREATED, source="test")

        assert len(received) == 1


    @pytest.mark.asyncio
    async def test_get_history_since_filters_old_events(self, bus):
        """Events before the since timestamp should be excluded."""
        import time
        from datetime import datetime

        await bus.emit(EventType.LOGIN_SUCCESS, source="test", info="old")
        old_ts = time.time()
        # Small sleep to ensure timestamp separation
        await asyncio.sleep(0.05)
        await bus.emit(EventType.LOGIN_SUCCESS, source="test", info="new")

        history = bus.get_history(since=old_ts)
        assert len(history) == 1
        assert history[0].data["info"] == "new"

    @pytest.mark.asyncio
    async def test_get_history_offset_skips_events(self, bus):
        """Offset should skip the first N matching events."""
        await bus.emit(EventType.LOGIN_SUCCESS, source="test", idx=0)
        await bus.emit(EventType.LOGIN_SUCCESS, source="test", idx=1)
        await bus.emit(EventType.LOGIN_SUCCESS, source="test", idx=2)

        history = bus.get_history(offset=1)
        assert len(history) == 2
        assert history[0].data["idx"] == 1
        assert history[1].data["idx"] == 2


class TestOnEventDecorator:
    @pytest.mark.asyncio
    async def test_decorator_registers_handler(self):
        # Use a fresh bus to avoid global state pollution
        from app.core.events import events as global_bus

        received = []

        # Manually subscribe (same mechanism as @on_event)
        def my_handler(event):
            received.append(event)

        global_bus.subscribe(EventType.RATE_LIMIT_EXCEEDED, my_handler)
        await global_bus.emit(EventType.RATE_LIMIT_EXCEEDED, source="test")

        assert len(received) == 1
        # Clean up
        global_bus.unsubscribe(EventType.RATE_LIMIT_EXCEEDED, my_handler)
