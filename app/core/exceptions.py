"""
Custom Exception Hierarchy for Spectra.

Provides structured error handling with proper exception chaining
and contextual information for debugging and monitoring.
"""

from typing import Any


class SpectraError(Exception):
    """Base exception for all Spectra errors.

    Attributes:
        message: Human-readable error message
        code: Machine-readable error code for API responses
        details: Additional context for debugging
    """

    code: str = "SPECTRA_ERROR"

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


# --- LLM Errors ---


class LLMError(SpectraError):
    """Base exception for LLM-related errors."""

    code = "LLM_ERROR"


class LLMConnectionError(LLMError):
    """Failed to connect to LLM service."""

    code = "LLM_CONNECTION_ERROR"

    def __init__(self, message: str = "Failed to connect to LLM service", host: str | None = None):
        super().__init__(message, details={"host": host})


class LLMResponseError(LLMError):
    """LLM returned an invalid or unexpected response."""

    code = "LLM_RESPONSE_ERROR"

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message, details={"status_code": status_code})


# --- Tool Errors ---


class ToolError(SpectraError):
    """Base exception for tool-related errors."""

    code = "TOOL_ERROR"


class ToolExecutionError(ToolError):
    """Tool execution failed."""

    code = "TOOL_EXECUTION_ERROR"

    def __init__(
        self,
        message: str,
        tool_id: str | None = None,
        exit_code: int | None = None,
        stderr: str | None = None,
    ):
        details = {
            "tool_id": tool_id,
            "exit_code": exit_code,
        }
        if stderr:
            details["stderr"] = stderr[:500]  # Truncate
        super().__init__(message, details=details)


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""

    code = "TOOL_TIMEOUT"

    def __init__(self, tool_id: str, timeout: int):
        super().__init__(
            f"Tool {tool_id} timed out after {timeout} seconds",
            details={"tool_id": tool_id, "timeout_seconds": timeout},
        )


class ToolNotFoundError(ToolError):
    """Requested tool not found in registry."""

    code = "TOOL_NOT_FOUND"

    def __init__(self, tool_id: str):
        super().__init__(f"Tool not found: {tool_id}", details={"tool_id": tool_id})


class ToolNotAvailableError(ToolError):
    """Tool exists but is not ready for use."""

    code = "TOOL_NOT_AVAILABLE"

    def __init__(self, tool_id: str, status: str):
        super().__init__(
            f"Tool {tool_id} is not available (status: {status})",
            details={"tool_id": tool_id, "status": status},
        )


# --- Mission Errors ---


class MissionError(SpectraError):
    """Base exception for mission-related errors."""

    code = "MISSION_ERROR"


class MissionNotFoundError(MissionError):
    """Mission not found."""

    code = "MISSION_NOT_FOUND"

    def __init__(self, mission_id: str):
        super().__init__(f"Mission not found: {mission_id}", details={"mission_id": mission_id})


class MissionStateError(MissionError):
    """Invalid state transition for mission."""

    code = "MISSION_STATE_ERROR"

    def __init__(self, mission_id: str, current_state: str, attempted_state: str):
        super().__init__(
            f"Cannot transition from {current_state} to {attempted_state}",
            details={
                "mission_id": mission_id,
                "current_state": current_state,
                "attempted_state": attempted_state,
            },
        )


class MissionPlanningError(MissionError):
    """Mission planning failed."""

    code = "MISSION_PLANNING_ERROR"


class MissionCancelledError(MissionError):
    """Mission was cancelled."""

    code = "MISSION_CANCELLED"

    def __init__(self, mission_id: str):
        super().__init__(f"Mission {mission_id} was cancelled", details={"mission_id": mission_id})


# --- Plugin Errors ---


class PluginError(SpectraError):
    """Base exception for plugin-related errors."""

    code = "PLUGIN_ERROR"


class PluginValidationError(PluginError):
    """Plugin validation failed."""

    code = "PLUGIN_VALIDATION_ERROR"


class PluginSignatureError(PluginError):
    """Plugin signature verification failed."""

    code = "PLUGIN_SIGNATURE_ERROR"


class PluginInstallationError(PluginError):
    """Plugin installation failed."""

    code = "PLUGIN_INSTALLATION_ERROR"

    def __init__(self, plugin_id: str, reason: str):
        super().__init__(
            f"Failed to install plugin {plugin_id}: {reason}",
            details={"plugin_id": plugin_id, "reason": reason},
        )


# --- Auth Errors ---


class AuthError(SpectraError):
    """Base exception for authentication errors."""

    code = "AUTH_ERROR"


class AuthenticationError(AuthError):
    """Authentication failed."""

    code = "AUTHENTICATION_FAILED"


class AuthorizationError(AuthError):
    """User not authorized for this action."""

    code = "AUTHORIZATION_FAILED"


class RateLimitError(AuthError):
    """Rate limit exceeded."""

    code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, limit: str, retry_after: int | None = None):
        super().__init__(
            f"Rate limit exceeded: {limit}",
            details={"limit": limit, "retry_after_seconds": retry_after},
        )


# --- Service Errors ---


class ServiceError(SpectraError):
    """Base exception for external service errors."""

    code = "SERVICE_ERROR"


class ServiceUnavailableError(ServiceError):
    """External service is unavailable."""

    code = "SERVICE_UNAVAILABLE"

    def __init__(self, service_name: str, reason: str | None = None):
        super().__init__(
            f"Service unavailable: {service_name}",
            details={"service": service_name, "reason": reason},
        )


class CircuitBreakerOpenError(ServiceError):
    """Circuit breaker is open, service calls blocked."""

    code = "CIRCUIT_BREAKER_OPEN"

    def __init__(self, service_name: str, recovery_time: int):
        super().__init__(
            f"Circuit breaker open for {service_name}",
            details={"service": service_name, "recovery_seconds": recovery_time},
        )


# --- Validation Errors ---


class ValidationError(SpectraError):
    """Input validation failed."""

    code = "VALIDATION_ERROR"

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message, details={"field": field})


class ConfigurationError(SpectraError):
    """Configuration error."""

    code = "CONFIGURATION_ERROR"


# --- Generic Resource Errors ---


class NotFoundError(SpectraError):
    """Generic resource not found."""

    code = "NOT_FOUND"

    def __init__(self, resource: str, identifier: str | None = None):
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} not found: {identifier}"
        super().__init__(msg, details={"resource": resource, "identifier": identifier})


class ExternalServiceError(ServiceError):
    """An external service (LLM, tool runner, etc.) failed."""

    code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service_name: str, reason: str | None = None):
        super().__init__(
            f"External service error: {service_name}",
            details={"service": service_name, "reason": reason},
        )


class RateLimitExceededError(SpectraError):
    """Rate limit exceeded (generic, non-auth)."""

    code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, limit: str, retry_after: int | None = None):
        super().__init__(
            f"Rate limit exceeded: {limit}",
            details={"limit": limit, "retry_after_seconds": retry_after},
        )


# --- HTTP Status Code Mapping ---

EXCEPTION_STATUS_MAP: dict[type[SpectraError], int] = {
    NotFoundError: 404,
    MissionNotFoundError: 404,
    ToolNotFoundError: 404,
    AuthenticationError: 401,
    AuthorizationError: 403,
    RateLimitError: 429,
    RateLimitExceededError: 429,
    ValidationError: 422,
    ConfigurationError: 500,
    ExternalServiceError: 502,
    ServiceUnavailableError: 503,
    CircuitBreakerOpenError: 503,
    LLMConnectionError: 502,
    ToolTimeoutError: 504,
    ToolExecutionError: 500,
    MissionStateError: 409,
    SpectraError: 500,
}


def get_status_code_for_exception(exc: SpectraError) -> int:
    """Return the HTTP status code for a SpectraError subclass."""
    for cls in type(exc).__mro__:
        if cls in EXCEPTION_STATUS_MAP:
            return EXCEPTION_STATUS_MAP[cls]
    return 500
