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

Note: Import lifespan directly from spectra_api.bootstrap.lifespan to avoid circular imports.
"""

import importlib as _importlib

# Lazy-load submodule symbols on first access to avoid import-time coupling.
# Consumers should import from specific submodules directly:
#   from spectra_platform.core.config import settings
#   from spectra_common.errors import SpectraError

_SUBMODULE_MAP: dict[str, str] = {
    # cache
    "CacheService": "spectra_platform.infrastructure.cache",
    "get_cache": "spectra_platform.infrastructure.cache",
    "set_cache": "spectra_platform.infrastructure.cache",
    # circuit_breaker
    "CircuitBreaker": "spectra_platform.infrastructure.circuit_breaker",
    "circuit_breakers": "spectra_platform.infrastructure.circuit_breaker",
    # config
    "get_settings": "spectra_platform.core.config",
    "settings": "spectra_platform.core.config",
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
    "async_session_maker": "spectra_platform.core.database",
    "engine": "spectra_platform.core.database",
    "get_async_session": "spectra_platform.core.database",
    # enums
    "AssessmentPhase": "spectra_platform.mission.core.enums",
    "EntityStatus": "spectra_platform.mission.core.enums",
    "MissionStatus": "spectra_platform.mission.core.enums",
    "Severity": "spectra_platform.mission.core.enums",
    # events
    "Event": "spectra_platform.infrastructure.events",
    "EventType": "spectra_platform.infrastructure.events",
    "events": "spectra_platform.infrastructure.events",
    # exceptions
    "AuthError": "spectra_common.errors",
    "LLMConnectionError": "spectra_common.errors",
    "LLMError": "spectra_common.errors",
    "MissionError": "spectra_common.errors",
    "MissionNotFoundError": "spectra_common.errors",
    "MissionStateError": "spectra_common.errors",
    "RateLimitError": "spectra_common.errors",
    "SpectraError": "spectra_common.errors",
    "ToolError": "spectra_common.errors",
    "ToolExecutionError": "spectra_common.errors",
    "ToolNotFoundError": "spectra_common.errors",
    "ValidationError": "spectra_common.errors",
    # protocols
    "HealthCheckable": "spectra_platform.di.protocols",
    # rate_limit
    "RateLimits": "spectra_platform.auth.rate_limit",
    "limiter": "spectra_platform.auth.rate_limit",
    # security
    "create_access_token": "spectra_platform.auth.security",
    "get_password_hash": "spectra_platform.auth.security",
    "verify_password": "spectra_platform.auth.security",
    # state_machine
    "MissionStateMachine": "spectra_platform.mission.core.state_machine",
    # telemetry
    "telemetry": "spectra_platform.telemetry.telemetry",
    "trace": "spectra_platform.telemetry.telemetry",
    # websocket
    "websocket_manager": "spectra_platform.mission.core.websocket",
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
