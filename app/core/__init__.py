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

Note: Import lifespan directly from app.bootstrap.lifespan to avoid circular imports.
"""

import importlib as _importlib

# Lazy-load submodule symbols on first access to avoid import-time coupling.
# Consumers should import from specific submodules directly:
#   from app.core.config import settings
#   from app.auth.exceptions import SpectraError

_SUBMODULE_MAP: dict[str, str] = {
    # cache
    "CacheService": "app.infrastructure.cache",
    "get_cache": "app.infrastructure.cache",
    "set_cache": "app.infrastructure.cache",
    # circuit_breaker
    "CircuitBreaker": "app.infrastructure.circuit_breaker",
    "circuit_breakers": "app.infrastructure.circuit_breaker",
    # config
    "get_settings": "app.core.config",
    "settings": "app.core.config",
    # constants
    "DEBRIEF_MAX_FINDINGS": "spectra_common.constants",
    "DEBRIEF_MAX_LOGS": "spectra_common.constants",
    "DEBRIEF_SUMMARY_LOG_CHARS": "spectra_common.constants",
    "EXPLOIT_OUTPUT_LOG_CHARS": "spectra_common.constants",
    "GO_COMPILE_TIMEOUT": "spectra_common.constants",
    "MAX_EXPLOIT_ITERATIONS": "spectra_common.constants",
    "MAX_HOSTS_DEFAULT": "spectra_common.constants",
    "SHELL_SOCKET_RECV_BYTES": "spectra_common.constants",
    # database
    "async_session_maker": "app.core.database",
    "engine": "app.core.database",
    "get_async_session": "app.core.database",
    # enums
    "AssessmentPhase": "app.mission.core.enums",
    "EntityStatus": "app.mission.core.enums",
    "MissionStatus": "app.mission.core.enums",
    "Severity": "app.mission.core.enums",
    # events
    "Event": "app.infrastructure.events",
    "EventType": "app.infrastructure.events",
    "events": "app.infrastructure.events",
    # exceptions
    "AuthError": "app.auth.exceptions",
    "LLMConnectionError": "app.auth.exceptions",
    "LLMError": "app.auth.exceptions",
    "MissionError": "app.auth.exceptions",
    "MissionNotFoundError": "app.auth.exceptions",
    "MissionStateError": "app.auth.exceptions",
    "RateLimitError": "app.auth.exceptions",
    "SpectraError": "app.auth.exceptions",
    "ToolError": "app.auth.exceptions",
    "ToolExecutionError": "app.auth.exceptions",
    "ToolNotFoundError": "app.auth.exceptions",
    "ValidationError": "app.auth.exceptions",
    # protocols
    "HealthCheckable": "app.di.protocols",
    # rate_limit
    "RateLimits": "app.auth.rate_limit",
    "limiter": "app.auth.rate_limit",
    # security
    "create_access_token": "app.auth.security",
    "get_password_hash": "app.auth.security",
    "verify_password": "app.auth.security",
    # state_machine
    "MissionState": "app.mission.core.state_machine",
    "MissionStateMachine": "app.mission.core.state_machine",
    # telemetry
    "telemetry": "app.telemetry.telemetry",
    "trace": "app.telemetry.telemetry",
    # websocket
    "websocket_manager": "app.mission.core.websocket",
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
