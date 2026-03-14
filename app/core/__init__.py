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

import importlib as _importlib

# Lazy-load submodule symbols on first access to avoid import-time coupling.
# Consumers should import from specific submodules directly:
#   from app.core.config import settings
#   from app.core.exceptions import SpectraError

_SUBMODULE_MAP: dict[str, str] = {
    # cache
    "CacheService": "app.core.cache",
    "get_cache": "app.core.cache",
    "set_cache": "app.core.cache",
    # circuit_breaker
    "CircuitBreaker": "app.core.circuit_breaker",
    "circuit_breakers": "app.core.circuit_breaker",
    # config
    "get_settings": "app.core.config",
    "settings": "app.core.config",
    # constants
    "DEBRIEF_MAX_FINDINGS": "app.core.constants",
    "DEBRIEF_MAX_LOGS": "app.core.constants",
    "DEBRIEF_SUMMARY_LOG_CHARS": "app.core.constants",
    "EXPLOIT_OUTPUT_LOG_CHARS": "app.core.constants",
    "GO_COMPILE_TIMEOUT": "app.core.constants",
    "MAX_EXPLOIT_ITERATIONS": "app.core.constants",
    "MAX_HOSTS_DEFAULT": "app.core.constants",
    "SHELL_SOCKET_RECV_BYTES": "app.core.constants",
    # database
    "async_session_maker": "app.core.database",
    "engine": "app.core.database",
    "get_async_session": "app.core.database",
    # enums
    "AssessmentPhase": "app.core.enums",
    "EntityStatus": "app.core.enums",
    "MissionStatus": "app.core.enums",
    "RiskLevel": "app.core.enums",
    "Severity": "app.core.enums",
    # events
    "Event": "app.core.events",
    "EventType": "app.core.events",
    "events": "app.core.events",
    # exceptions
    "AuthError": "app.core.exceptions",
    "LLMConnectionError": "app.core.exceptions",
    "LLMError": "app.core.exceptions",
    "MissionError": "app.core.exceptions",
    "MissionNotFoundError": "app.core.exceptions",
    "MissionStateError": "app.core.exceptions",
    "RateLimitError": "app.core.exceptions",
    "SpectraError": "app.core.exceptions",
    "ToolError": "app.core.exceptions",
    "ToolExecutionError": "app.core.exceptions",
    "ToolNotFoundError": "app.core.exceptions",
    "ValidationError": "app.core.exceptions",
    # protocols
    "HealthCheckable": "app.core.protocols",
    # rate_limit
    "RateLimits": "app.core.rate_limit",
    "limiter": "app.core.rate_limit",
    # security
    "create_access_token": "app.core.security",
    "get_password_hash": "app.core.security",
    "verify_password": "app.core.security",
    # state_machine
    "MissionState": "app.core.state_machine",
    "MissionStateMachine": "app.core.state_machine",
    # telemetry
    "telemetry": "app.core.telemetry",
    "trace": "app.core.telemetry",
    # websocket
    "websocket_manager": "app.core.websocket",
}


def __getattr__(name: str):
    mod_path = _SUBMODULE_MAP.get(name)
    if mod_path is not None:
        # Alias: websocket_manager lives as 'manager' in the submodule
        attr_name = "manager" if name == "websocket_manager" else name
        mod = _importlib.import_module(mod_path)
        val = getattr(mod, attr_name)
        globals()[name] = val  # cache for subsequent access
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_SUBMODULE_MAP.keys())
