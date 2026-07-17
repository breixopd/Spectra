"""
Circuit Breaker Pattern Implementation.

Prevents cascading failures by temporarily blocking calls to failing services.
Implements the standard circuit breaker states: CLOSED, OPEN, HALF_OPEN.
State is persisted via the CacheService (PostgreSQL-backed).
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from spectra_common.errors import CircuitBreakerOpenError
from spectra_infra.events import EventType, events

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Failing, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    # Number of failures before opening circuit
    failure_threshold: int = 5

    # Time in seconds before attempting recovery
    recovery_timeout: int = 30

    # Number of successful calls needed to close circuit
    success_threshold: int = 2

    # Exceptions that trigger the circuit breaker
    expected_exceptions: tuple[type[Exception], ...] = (Exception,)

    # Optional: specific exceptions to exclude
    excluded_exceptions: tuple[type[Exception], ...] = ()


@dataclass
class CircuitBreakerState:
    """Current state of a circuit breaker."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    opened_at: float | None = None

    # Statistics
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    times_opened: int = 0


class CircuitBreaker:
    """
    Circuit breaker implementation.

    Usage:
        breaker = CircuitBreaker("ollama", config)

        @breaker
        async def call_ollama():
            ...

        # Or manually:
        async with breaker:
            await call_ollama()
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._validate_exception_config()
        self._state = CircuitBreakerState()
        self._lock = asyncio.Lock()
        self._state_loaded = False

    async def _get_persisted_state(self) -> CircuitBreakerState | None:
        from spectra_infra.cache import get_cache

        cache = get_cache()
        if not cache:
            return None

        key = f"circuit:{self.name}"
        data = await cache.get(key)
        if not data:
            return None

        try:
            state_dict = data if isinstance(data, dict) else json.loads(data)
            state_dict["state"] = CircuitState(state_dict["state"])
            return CircuitBreakerState(**state_dict)
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Failed to deserialize circuit state: %s", e)
            return None

    async def _save_persisted_state(self):
        from spectra_infra.cache import get_cache

        cache = get_cache()
        if not cache:
            return

        key = f"circuit:{self.name}"
        state_dict = asdict(self._state)
        state_dict["state"] = state_dict["state"].value
        await cache.set(key, state_dict, ttl=3600)

    def _validate_exception_config(self) -> None:
        """Validate that exception tuples contain proper Exception subclasses."""
        for exc in self.config.expected_exceptions:
            if not isinstance(exc, type) or not issubclass(exc, BaseException):
                raise TypeError(f"expected_exceptions must contain Exception types, got {exc}")
        for exc in self.config.excluded_exceptions:
            if not isinstance(exc, type) or not issubclass(exc, BaseException):
                raise TypeError(f"excluded_exceptions must contain Exception types, got {exc}")

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state.state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state.state == CircuitState.OPEN

    async def _check_state(self) -> None:
        """Check and potentially transition state."""
        if not self._state_loaded:
            persisted = await self._get_persisted_state()
            if persisted:
                self._state = persisted
            self._state_loaded = True
        async with self._lock:
            if self._state.state == CircuitState.OPEN and self._state.opened_at:
                elapsed = time.time() - self._state.opened_at
                if elapsed >= self.config.recovery_timeout:
                    self._transition_to_half_open()

    def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        self._state.state = CircuitState.OPEN
        self._state.opened_at = time.time()
        self._state.times_opened += 1
        self._state.success_count = 0

        logger.warning(
            "Circuit breaker '%s' OPENED after %d failures",
            self.name,
            self._state.failure_count,
        )

        events.emit_sync(
            EventType.CIRCUIT_BREAKER_OPENED,
            source="circuit_breaker",
            service=self.name,
            failure_count=self._state.failure_count,
        )

    def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        self._state.state = CircuitState.HALF_OPEN
        self._state.success_count = 0

        logger.info("Circuit breaker '%s' entering HALF_OPEN state", self.name)

    def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        self._state.state = CircuitState.CLOSED
        self._state.failure_count = 0
        self._state.success_count = 0
        self._state.opened_at = None

        logger.info("Circuit breaker '%s' CLOSED", self.name)

        events.emit_sync(
            EventType.CIRCUIT_BREAKER_CLOSED,
            source="circuit_breaker",
            service=self.name,
        )

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._state.success_count += 1
            self._state.total_successes += 1
            self._state.last_success_time = time.time()

            if (
                self._state.state == CircuitState.HALF_OPEN
                and self._state.success_count >= self.config.success_threshold
            ):
                self._transition_to_closed()

            await self._save_persisted_state()

    async def _record_failure(self, exc: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._state.failure_count += 1
            self._state.total_failures += 1
            self._state.last_failure_time = time.time()

            if self._state.state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately opens
                self._transition_to_open()
            elif (
                self._state.state == CircuitState.CLOSED and self._state.failure_count >= self.config.failure_threshold
            ):
                self._transition_to_open()

            await self._save_persisted_state()

    def _should_allow_request(self) -> bool:
        """Determine if a request should be allowed."""
        return self._state.state != CircuitState.OPEN

    async def call(self, func: Callable[P, T | Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
        """
        Execute a function through the circuit breaker.

        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        # Sync persisted state
        persisted_state = await self._get_persisted_state()
        if persisted_state:
            self._state = persisted_state

        await self._check_state()

        if not self._should_allow_request():
            recovery_time = self.config.recovery_timeout
            if self._state.opened_at:
                elapsed = time.time() - self._state.opened_at
                recovery_time = max(0, int(self.config.recovery_timeout - elapsed))

            raise CircuitBreakerOpenError(self.name, recovery_time)

        self._state.total_calls += 1

        try:
            result = func(*args, **kwargs)
            if isinstance(result, Awaitable):
                result = await result
            await self._record_success()
            return cast(T, result)
        except self.config.excluded_exceptions:  # pylint: disable=catching-non-exception
            # Don't count excluded exceptions (validated at init)
            raise
        except self.config.expected_exceptions as e:  # pylint: disable=catching-non-exception
            # Count expected exceptions as failures (validated at init)
            await self._record_failure(e)
            raise

    def __call__(self, func: Callable[P, T | Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        """Decorator to wrap a function with circuit breaker."""

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await self.call(func, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry."""
        # Sync persisted state
        persisted_state = await self._get_persisted_state()
        if persisted_state:
            self._state = persisted_state

        await self._check_state()

        if not self._should_allow_request():
            recovery_time = self.config.recovery_timeout
            if self._state.opened_at:
                elapsed = time.time() - self._state.opened_at
                recovery_time = max(0, int(self.config.recovery_timeout - elapsed))
            raise CircuitBreakerOpenError(self.name, recovery_time)

        self._state.total_calls += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit."""
        if exc_type is None:
            await self._record_success()
        elif issubclass(exc_type, self.config.expected_exceptions) and not issubclass(
            exc_type, self.config.excluded_exceptions
        ):
            await self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.state.value,
            "failure_count": self._state.failure_count,
            "success_count": self._state.success_count,
            "total_calls": self._state.total_calls,
            "total_failures": self._state.total_failures,
            "total_successes": self._state.total_successes,
            "times_opened": self._state.times_opened,
            "failure_rate": (
                self._state.total_failures / self._state.total_calls * 100 if self._state.total_calls > 0 else 0
            ),
        }

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitBreakerState()
        logger.info("Circuit breaker '%s' manually reset", self.name)


# --- Circuit Breaker Registry ---


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker by name."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all circuit breakers."""
        return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for cb in self._breakers.values():
            cb.reset()


# Global registry
circuit_breakers = CircuitBreakerRegistry()


# Pre-configured circuit breakers for common services
def get_llm_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for LLM service."""
    return circuit_breakers.get(
        "llm",
        CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=60,
            success_threshold=2,
        ),
    )


def get_cache_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for cache/DB layer."""
    return circuit_breakers.get(
        "cache",
        CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=30,
            success_threshold=3,
        ),
    )


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    "circuit_breakers",
    "get_cache_circuit_breaker",
    "get_llm_circuit_breaker",
]
