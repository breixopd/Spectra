"""Core application components: config, lifecycle, state, utilities.

This module provides the foundational infrastructure for the Spectra platform:
- Configuration management (settings)
- Database connection handling
- Security utilities (JWT, password hashing)
- Application lifecycle management
- WebSocket connection management
- Event system (pub/sub)
- Caching layer
- Rate limiting
- Circuit breaker pattern
- Telemetry and observability
- Custom exceptions
- Protocol interfaces

Note: Import lifespan directly from app.core.lifespan to avoid circular imports.
"""

from app.core.cache import CacheService, get_cache, set_cache
from app.core.circuit_breaker import CircuitBreaker, circuit_breakers
from app.core.config import get_settings, settings
from app.core.constants import (
    DEBRIEF_MAX_FINDINGS,
    DEBRIEF_MAX_LOGS,
    DEBRIEF_SUMMARY_LOG_CHARS,
    EXPLOIT_OUTPUT_LOG_CHARS,
    GO_COMPILE_TIMEOUT,
    MAX_EXPLOIT_ITERATIONS,
    MAX_HOSTS_DEFAULT,
    SHELL_SOCKET_RECV_BYTES,
)
from app.core.database import async_session_maker, engine, get_async_session
from app.core.enums import (
    AssessmentPhase,
    EntityStatus,
    MissionStatus,
    RiskLevel,
    Severity,
)
from app.core.events import Event, EventType, events
from app.core.exceptions import (
    AuthError,
    LLMConnectionError,
    LLMError,
    LLMTimeoutError,
    MissionError,
    MissionNotFoundError,
    MissionStateError,
    RateLimitError,
    SpectraError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
)
from app.core.protocols import (
    Broadcastable,
    Executable,
    HealthCheckable,
    Loggable,
    Serializable,
)
from app.core.rate_limit import RateLimits, limiter
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.core.state_machine import MissionState, MissionStateMachine
from app.core.telemetry import telemetry, trace
from app.core.websocket import manager as websocket_manager

__all__ = [
    # Config
    "settings",
    "get_settings",
    # Constants
    "MAX_HOSTS_DEFAULT",
    "MAX_EXPLOIT_ITERATIONS",
    "EXPLOIT_OUTPUT_LOG_CHARS",
    "GO_COMPILE_TIMEOUT",
    "SHELL_SOCKET_RECV_BYTES",
    "DEBRIEF_MAX_FINDINGS",
    "DEBRIEF_MAX_LOGS",
    "DEBRIEF_SUMMARY_LOG_CHARS",
    # Database
    "get_async_session",
    "async_session_maker",
    "engine",
    # Security
    "create_access_token",
    "verify_password",
    "get_password_hash",
    # WebSocket
    "websocket_manager",
    # Enums
    "AssessmentPhase",
    "EntityStatus",
    "Severity",
    "RiskLevel",
    "MissionStatus",
    # Exceptions
    "SpectraError",
    "LLMError",
    "LLMTimeoutError",
    "LLMConnectionError",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "MissionError",
    "MissionNotFoundError",
    "MissionStateError",
    "AuthError",
    "RateLimitError",
    "ValidationError",
    # Events
    "events",
    "EventType",
    "Event",
    # Cache
    "CacheService",
    "get_cache",
    "set_cache",
    # Rate Limiting
    "limiter",
    "RateLimits",
    # Circuit Breaker
    "CircuitBreaker",
    "circuit_breakers",
    # Telemetry
    "telemetry",
    "trace",
    # State Machine
    "MissionState",
    "MissionStateMachine",
    # Protocols
    "Broadcastable",
    "Loggable",
    "Serializable",
    "Executable",
    "HealthCheckable",
]
