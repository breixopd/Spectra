"""Unit tests for app.core.circuit_breaker module."""

import time

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerRegistry,
)
from app.core.exceptions import CircuitBreakerOpenError


def _make_breaker(failure_threshold=3, recovery_timeout=30, success_threshold=2):
    """Helper to build a CircuitBreaker with custom config."""
    cfg = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        success_threshold=success_threshold,
    )
    return CircuitBreaker("test-svc", cfg)


@pytest.fixture(autouse=True)
def _patch_cache_and_events():
    """Prevent real Redis/event-bus calls in every test."""
    with (
        patch("app.core.cache.get_cache", return_value=None),
        patch("app.core.circuit_breaker.events") as mock_events,
    ):
        mock_events.emit_sync = MagicMock()
        yield


class TestCircuitBreakerClosedState:
    """Tests for normal (CLOSED) operation."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        cb = _make_breaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed is True

    @pytest.mark.asyncio
    async def test_successful_call_keeps_closed(self):
        cb = _make_breaker()
        func = AsyncMock(return_value="ok")

        result = await cb.call(func)

        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_single_failure_stays_closed(self):
        """One failure is below the threshold."""
        cb = _make_breaker(failure_threshold=3)
        func = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            await cb.call(func)

        assert cb.state == CircuitState.CLOSED
        assert cb._state.failure_count == 1


class TestCircuitBreakerOpenState:
    """Tests for the OPEN state transition and behaviour."""

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = _make_breaker(failure_threshold=2)
        func = AsyncMock(side_effect=RuntimeError("fail"))

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(func)

        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_open_circuit_raises_circuit_breaker_error(self):
        cb = _make_breaker(failure_threshold=1, recovery_timeout=600)
        func = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            await cb.call(func)

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(func)

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_context_manager(self):
        """__aenter__ also raises when circuit is open."""
        cb = _make_breaker(failure_threshold=1, recovery_timeout=600)
        cb._state.state = CircuitState.OPEN
        cb._state.opened_at = time.time()

        with pytest.raises(CircuitBreakerOpenError):
            async with cb:
                pass  # pragma: no cover


class TestCircuitBreakerHalfOpen:
    """Tests for HALF_OPEN recovery behaviour."""

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0)
        cb._state.state = CircuitState.OPEN
        cb._state.opened_at = time.time() - 1

        await cb._check_state()

        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0, success_threshold=1)
        cb._state.state = CircuitState.HALF_OPEN

        func = AsyncMock(return_value="recovered")
        result = await cb.call(func)

        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0, success_threshold=2)
        cb._state.state = CircuitState.HALF_OPEN
        func = AsyncMock(side_effect=RuntimeError("still broken"))

        with pytest.raises(RuntimeError):
            await cb.call(func)

        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerStats:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_track_calls(self):
        cb = _make_breaker()
        func = AsyncMock(return_value="ok")

        await cb.call(func)
        await cb.call(func)

        stats = cb.get_stats()
        assert stats["total_calls"] == 2
        assert stats["total_successes"] == 2
        assert stats["total_failures"] == 0

    @pytest.mark.asyncio
    async def test_stats_track_failures(self):
        cb = _make_breaker(failure_threshold=5)
        func = AsyncMock(side_effect=RuntimeError("err"))

        with pytest.raises(RuntimeError):
            await cb.call(func)

        stats = cb.get_stats()
        assert stats["total_failures"] == 1
        assert stats["failure_rate"] == 100.0

    def test_reset_clears_state(self):
        cb = _make_breaker()
        cb._state.failure_count = 5
        cb._state.state = CircuitState.OPEN

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb._state.failure_count == 0


class TestCircuitBreakerContextManager:
    """Tests for async context manager protocol."""

    @pytest.mark.asyncio
    async def test_context_manager_records_success(self):
        cb = _make_breaker()

        async with cb:
            pass

        assert cb._state.total_successes == 1

    @pytest.mark.asyncio
    async def test_context_manager_records_failure(self):
        cb = _make_breaker(failure_threshold=5)

        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("oops")

        assert cb._state.total_failures == 1


class TestCircuitBreakerRegistry:
    """Tests for the registry helper."""

    def test_get_creates_new_breaker(self):
        reg = CircuitBreakerRegistry()
        cb = reg.get("svc-a")
        assert isinstance(cb, CircuitBreaker)
        assert cb.name == "svc-a"

    def test_get_returns_same_instance(self):
        reg = CircuitBreakerRegistry()
        cb1 = reg.get("svc-a")
        cb2 = reg.get("svc-a")
        assert cb1 is cb2

    def test_get_all_stats(self):
        reg = CircuitBreakerRegistry()
        reg.get("alpha")
        reg.get("beta")
        stats = reg.get_all_stats()
        assert "alpha" in stats
        assert "beta" in stats
