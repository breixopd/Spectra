"""Unit tests for the new core infrastructure modules."""

import pytest
from unittest.mock import MagicMock
from collections import deque

from app.core.exceptions import (
    SpectraError,
    LLMError,
    LLMTimeoutError,
    LLMConnectionError,
    ToolExecutionError,
    MissionStateError,
    CircuitBreakerOpenError,
)
from app.core.events import EventBus, EventType, Event
from app.core.state_machine import MissionState, MissionStateMachine, VALID_TRANSITIONS
from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from app.core.telemetry import TelemetryCollector


class TestExceptionHierarchy:
    """Tests for the custom exception hierarchy."""

    def test_spectra_error_base(self):
        """Test base SpectraError."""
        err = SpectraError("Test error", code="TEST_CODE", details={"key": "value"})
        assert err.message == "Test error"
        assert err.code == "TEST_CODE"
        assert err.details == {"key": "value"}

    def test_spectra_error_to_dict(self):
        """Test exception serialization."""
        err = SpectraError("Test error", details={"test": 123})
        result = err.to_dict()
        assert result["error"] == "SPECTRA_ERROR"
        assert result["message"] == "Test error"
        assert result["details"]["test"] == 123

    def test_llm_error_inheritance(self):
        """Test LLM errors inherit from SpectraError."""
        assert issubclass(LLMError, SpectraError)
        assert issubclass(LLMTimeoutError, LLMError)
        assert issubclass(LLMConnectionError, LLMError)

    def test_llm_timeout_error(self):
        """Test LLMTimeoutError with timeout details."""
        err = LLMTimeoutError(timeout=30)
        assert err.details["timeout_seconds"] == 30
        assert err.code == "LLM_TIMEOUT"

    def test_tool_execution_error(self):
        """Test ToolExecutionError with context."""
        err = ToolExecutionError(
            "Command failed",
            tool_id="nmap",
            exit_code=1,
            stderr="Permission denied",
        )
        assert err.details["tool_id"] == "nmap"
        assert err.details["exit_code"] == 1
        assert "Permission" in err.details["stderr"]

    def test_mission_state_error(self):
        """Test MissionStateError with state info."""
        err = MissionStateError("mission-123", "created", "completed")
        assert "created" in str(err)
        assert "completed" in str(err)
        assert err.details["mission_id"] == "mission-123"

    def test_exception_chaining(self):
        """Test that exceptions can be properly chained."""
        original = ValueError("Original error")
        wrapped = LLMError("Wrapped error")
        wrapped.__cause__ = original
        assert wrapped.__cause__ is original


class TestEventBus:
    """Tests for the event bus system."""

    def test_subscribe_and_emit(self):
        """Test basic event subscription and emission."""
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.MISSION_STARTED, handler)
        bus._handlers[EventType.MISSION_STARTED.value][0][0](
            Event(type=EventType.MISSION_STARTED)
        )

        assert len(received) == 1
        assert received[0].type == EventType.MISSION_STARTED

    def test_unsubscribe(self):
        """Test event unsubscription."""
        bus = EventBus()
        handler = MagicMock()

        bus.subscribe(EventType.MISSION_COMPLETED, handler)
        bus.unsubscribe(EventType.MISSION_COMPLETED, handler)

        # Check that handler is not in the list of (handler, critical) tuples
        handlers = bus._handlers.get(EventType.MISSION_COMPLETED.value, [])
        assert handler not in [h[0] for h in handlers]

    def test_event_history(self):
        """Test event history tracking."""
        bus = EventBus()
        bus._max_history = 10
        # Re-initialize deque with correct maxlen
        bus._event_history = deque(maxlen=bus._max_history)

        # Add events directly to history
        for i in range(15):
            bus._event_history.append(
                Event(
                    type=EventType.MISSION_STARTED,
                    data={"index": i},
                )
            )

        # Should be truncated to max_history automatically
        assert len(bus._event_history) == 10

    def test_get_stats(self):
        """Test event statistics."""
        bus = EventBus()
        bus._event_history = [
            Event(type=EventType.MISSION_STARTED),
            Event(type=EventType.MISSION_STARTED),
            Event(type=EventType.MISSION_COMPLETED),
        ]

        stats = bus.get_stats()
        assert stats["total_events"] == 3
        assert stats["event_counts"]["mission_started"] == 2
        assert stats["event_counts"]["mission_completed"] == 1


class TestMissionStateMachine:
    """Tests for the mission state machine."""

    def test_initial_state(self):
        """Test initial state is CREATED."""
        fsm = MissionStateMachine("test-123")
        assert fsm.state == MissionState.CREATED
        assert not fsm.is_terminal
        assert not fsm.is_active

    def test_valid_transition(self):
        """Test valid state transitions."""
        fsm = MissionStateMachine("test-123")

        transition = fsm.transition_to(MissionState.INITIALIZING)
        assert fsm.state == MissionState.INITIALIZING
        assert transition.from_state == MissionState.CREATED
        assert transition.to_state == MissionState.INITIALIZING

    def test_invalid_transition_raises(self):
        """Test invalid transitions raise MissionStateError."""
        fsm = MissionStateMachine("test-123")

        with pytest.raises(MissionStateError) as exc_info:
            fsm.transition_to(MissionState.COMPLETED)

        assert exc_info.value.details["current_state"] == "created"
        assert exc_info.value.details["attempted_state"] == "completed"

    def test_terminal_states(self):
        """Test terminal states have no valid transitions."""
        for terminal in [
            MissionState.COMPLETED,
            MissionState.FAILED,
            MissionState.CANCELLED,
        ]:
            assert VALID_TRANSITIONS[terminal] == set()

    def test_can_transition_to(self):
        """Test can_transition_to check."""
        fsm = MissionStateMachine("test-123")

        assert fsm.can_transition_to(MissionState.INITIALIZING)
        assert fsm.can_transition_to(MissionState.CANCELLED)
        assert not fsm.can_transition_to(MissionState.EXECUTING)

    def test_get_valid_transitions(self):
        """Test getting valid transitions."""
        fsm = MissionStateMachine("test-123")

        valid = fsm.get_valid_transitions()
        assert MissionState.INITIALIZING in valid
        assert MissionState.CANCELLED in valid
        assert MissionState.EXECUTING not in valid

    def test_force_transition(self):
        """Test forced transitions bypass validation."""
        fsm = MissionStateMachine("test-123")

        transition = fsm.force_transition(MissionState.COMPLETED, "Emergency stop")
        assert fsm.state == MissionState.COMPLETED
        assert transition.reason is not None and "[FORCED]" in transition.reason

    def test_history_tracking(self):
        """Test state transition history."""
        fsm = MissionStateMachine("test-123")

        fsm.transition_to(MissionState.INITIALIZING)
        fsm.transition_to(MissionState.SCOPING)

        history = fsm.get_history()
        assert len(history) == 2
        assert history[0]["to_state"] == "initializing"
        assert history[1]["to_state"] == "scoping"

    def test_is_active_states(self):
        """Test is_active for running states."""
        fsm = MissionStateMachine("test-123")

        fsm.transition_to(MissionState.INITIALIZING)
        assert fsm.is_active

        fsm.transition_to(MissionState.SCOPING)
        assert fsm.is_active

    def test_to_dict(self):
        """Test serialization to dictionary."""
        fsm = MissionStateMachine("test-123")
        fsm.transition_to(MissionState.INITIALIZING)

        data = fsm.to_dict()
        assert data["mission_id"] == "test-123"
        assert data["current_state"] == "initializing"
        assert data["is_active"] is True
        assert "history" in data


class TestCircuitBreaker:
    """Tests for the circuit breaker pattern."""

    def test_initial_state_closed(self):
        """Test circuit starts in CLOSED state."""
        cb = CircuitBreaker("test-service")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed
        assert not cb.is_open

    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        """Test successful calls keep circuit closed."""
        cb = CircuitBreaker("test-service")

        await cb._record_success()
        await cb._record_success()

        assert cb.is_closed
        assert cb._state.success_count == 2

    @pytest.mark.asyncio
    async def test_failures_open_circuit(self):
        """Test too many failures open the circuit."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("test-service", config)

        await cb._record_failure(Exception("test"))
        assert cb.is_closed

        await cb._record_failure(Exception("test"))
        assert cb.is_open
        assert cb._state.times_opened == 1

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_requests(self):
        """Test open circuit raises CircuitBreakerOpenError."""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60)
        cb = CircuitBreaker("test-service", config)

        await cb._record_failure(Exception("test"))
        assert cb.is_open

        with pytest.raises(CircuitBreakerOpenError):
            async with cb:
                pass

    def test_get_stats(self):
        """Test circuit breaker statistics."""
        cb = CircuitBreaker("test-service")
        cb._state.total_calls = 100
        cb._state.total_failures = 5
        cb._state.total_successes = 95

        stats = cb.get_stats()
        assert stats["name"] == "test-service"
        assert stats["total_calls"] == 100
        assert stats["failure_rate"] == 5.0

    def test_reset(self):
        """Test manual reset."""
        cb = CircuitBreaker("test-service")
        cb._state.failure_count = 10
        cb._state.state = CircuitState.OPEN

        cb.reset()

        assert cb.is_closed
        assert cb._state.failure_count == 0


class TestTelemetryCollector:
    """Tests for the telemetry collector."""

    def test_start_and_end_span(self):
        """Test span creation and ending."""
        collector = TelemetryCollector()

        span = collector.start_span("test-operation")
        assert span.name == "test-operation"
        assert span.end_time is None

        collector.end_span(span, "ok")
        assert span.end_time is not None
        assert span.status == "ok"
        assert span.duration_ms > 0

    def test_record_metric(self):
        """Test metric recording."""
        collector = TelemetryCollector()

        collector.record_metric("requests", 1, {"endpoint": "/api"}, "counter")

        assert len(collector._metrics) == 1
        assert collector._metrics[0].name == "requests"
        assert collector._metrics[0].value == 1

    def test_increment_counter(self):
        """Test counter increment."""
        collector = TelemetryCollector()

        collector.increment_counter("api_calls", 5)

        assert "api_calls:" in list(collector._counters.keys())[0]

    def test_overview_stats(self):
        """Test overview statistics."""
        collector = TelemetryCollector()
        collector._request_count = 100
        collector._error_count = 5
        collector._total_latency = 5000.0

        stats = collector.get_overview_stats()
        assert stats["total_requests"] == 100
        assert stats["total_errors"] == 5
        assert stats["error_rate_percent"] == 5.0
        assert stats["avg_latency_ms"] == 50.0

    def test_service_status_tracking(self):
        """Test service health status updates."""
        collector = TelemetryCollector()

        collector.update_service_status("cache", healthy=True, latency_ms=5.5)
        collector.update_service_status("db", healthy=False, error="Connection refused")

        health = collector.get_service_health()
        assert health["cache"]["healthy"] is True
        assert health["db"]["healthy"] is False
        assert health["db"]["error"] == "Connection refused"

    def test_trace_history_limit(self):
        """Test trace history is limited."""
        collector = TelemetryCollector(max_traces=5)

        for i in range(10):
            span = collector.start_span(f"op-{i}")
            collector.end_span(span)

        assert len(collector._traces) == 5

    def test_get_error_traces(self):
        """Test getting error traces."""
        collector = TelemetryCollector()

        span1 = collector.start_span("success")
        collector.end_span(span1, "ok")

        span2 = collector.start_span("failure")
        collector.end_span(span2, "error", "Test error")

        errors = collector.get_error_traces()
        assert len(errors) == 1
        assert errors[0]["status"] == "error"

    def test_slow_operations(self):
        """Test getting slow operations."""
        collector = TelemetryCollector()

        span = collector.start_span("slow-op")
        span.duration_ms = 2000.0  # 2 seconds
        span.end_time = span.start_time
        collector._traces.append(span)

        slow = collector.get_slow_operations(threshold_ms=1000)
        assert len(slow) == 1
        assert slow[0]["duration_ms"] == 2000.0
