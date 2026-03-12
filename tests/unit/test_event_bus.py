"""Tests for app.services.ai.event_bus.AgentEventBus."""

import asyncio

import pytest

from app.services.ai.event_bus import AgentEventBus, AgentMessage


@pytest.mark.asyncio
class TestPubSub:
    async def test_subscribe_and_publish(self):
        bus = AgentEventBus()
        received = []

        async def handler(msg: AgentMessage):
            received.append(msg)

        bus.subscribe("recon", handler)
        msg = AgentMessage(sender="agent-a", topic="recon", payload={"data": 1})
        await bus.publish(msg)
        assert len(received) == 1
        assert received[0].payload == {"data": 1}

    async def test_multiple_subscribers(self):
        bus = AgentEventBus()
        results = []

        async def h1(msg):
            results.append("h1")

        async def h2(msg):
            results.append("h2")

        bus.subscribe("topic", h1)
        bus.subscribe("topic", h2)
        await bus.publish(AgentMessage(sender="s", topic="topic", payload=None))
        assert set(results) == {"h1", "h2"}

    async def test_no_cross_topic_delivery(self):
        bus = AgentEventBus()
        received = []

        async def handler(msg):
            received.append(msg)

        bus.subscribe("topicA", handler)
        await bus.publish(AgentMessage(sender="s", topic="topicB", payload=None))
        assert len(received) == 0

    async def test_unsubscribe(self):
        bus = AgentEventBus()
        received = []

        async def handler(msg):
            received.append(msg)

        bus.subscribe("t", handler)
        bus.unsubscribe("t", handler)
        await bus.publish(AgentMessage(sender="s", topic="t", payload=None))
        assert len(received) == 0

    async def test_unsubscribe_nonexistent_handler(self):
        bus = AgentEventBus()

        async def handler(msg):
            pass

        # Should not raise
        bus.unsubscribe("t", handler)


@pytest.mark.asyncio
class TestDirectQueue:
    async def test_send_and_receive(self):
        bus = AgentEventBus()
        msg = AgentMessage(sender="agent-a", topic="direct", payload="hello")
        await bus.send_direct("agent-b", msg)
        received = await bus.receive_direct("agent-b", timeout=1.0)
        assert received is not None
        assert received.payload == "hello"

    async def test_empty_queue_returns_none(self):
        bus = AgentEventBus()
        result = await bus.receive_direct("agent-x", timeout=0.1)
        assert result is None

    async def test_fifo_ordering(self):
        bus = AgentEventBus()
        for i in range(3):
            await bus.send_direct("agent-c", AgentMessage(
                sender="s", topic="d", payload=i))
        for i in range(3):
            msg = await bus.receive_direct("agent-c", timeout=1.0)
            assert msg is not None
            assert msg.payload == i


@pytest.mark.asyncio
class TestHistory:
    async def test_history_recorded(self):
        bus = AgentEventBus()
        await bus.publish(AgentMessage(sender="s", topic="t", payload="p"))
        history = bus.get_history()
        assert len(history) == 1

    async def test_history_filtered_by_topic(self):
        bus = AgentEventBus()
        await bus.publish(AgentMessage(sender="s", topic="a", payload=1))
        await bus.publish(AgentMessage(sender="s", topic="b", payload=2))
        assert len(bus.get_history(topic="a")) == 1

    async def test_history_capped(self):
        bus = AgentEventBus()
        bus._max_history = 5
        for i in range(10):
            await bus.publish(AgentMessage(sender="s", topic="t", payload=i))
        assert len(bus.get_history()) == 5
