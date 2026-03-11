"""
Standardized API error response helpers.

Provides consistent error response formatting across all API endpoints.
New endpoints should use these helpers. Existing endpoints will be
migrated incrementally.

Usage:
    from app.api.error_responses import not_found, forbidden, bad_request

    raise not_found("Target", target_id)
    raise forbidden("Not authorized to access this resource")
    raise bad_request("Invalid input", error_code="INVALID_INPUT")
"""

from fastapi import HTTPException, status


def _build(status_code: int, detail: str, error_code: str) -> HTTPException:
    """Build an HTTPException with a consistent detail payload."""
    return HTTPException(
        status_code=status_code,
        detail={
            "detail": detail,
            "error_code": error_code,
            "status": status_code,
        },
    )


def not_found(resource: str, resource_id: str | None = None) -> HTTPException:
    """404 Not Found."""
    msg = f"{resource} not found" if not resource_id else f"{resource} '{resource_id}' not found"
    return _build(status.HTTP_404_NOT_FOUND, msg, "NOT_FOUND")


def forbidden(detail: str = "Not authorized") -> HTTPException:
    """403 Forbidden."""
    return _build(status.HTTP_403_FORBIDDEN, detail, "FORBIDDEN")


def bad_request(detail: str, error_code: str = "BAD_REQUEST") -> HTTPException:
    """400 Bad Request."""
    return _build(status.HTTP_400_BAD_REQUEST, detail, error_code)


def conflict(detail: str, error_code: str = "CONFLICT") -> HTTPException:
    """409 Conflict."""
    return _build(status.HTTP_409_CONFLICT, detail, error_code)


def unauthorized(detail: str = "Authentication required") -> HTTPException:
    """401 Unauthorized."""
    return _build(status.HTTP_401_UNAUTHORIZED, detail, "UNAUTHORIZED")


def rate_limited(detail: str = "Rate limit exceeded", retry_after: int | None = None) -> HTTPException:
    """429 Too Many Requests."""
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "detail": detail,
            "error_code": "RATE_LIMITED",
            "status": 429,
        },
        headers=headers,
    )


def internal_error(detail: str = "Internal server error") -> HTTPException:
    """500 Internal Server Error."""
    return _build(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, "INTERNAL_ERROR")
