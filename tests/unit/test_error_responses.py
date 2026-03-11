"""
Tests for standardized API error response helpers.
"""

from fastapi import HTTPException

from app.api.error_responses import (
    _build,
    bad_request,
    conflict,
    forbidden,
    internal_error,
    not_found,
    rate_limited,
    unauthorized,
)


class TestBuildHelper:
    """Tests for the internal _build function."""

    def test_returns_http_exception(self):
        exc = _build(400, "bad", "BAD")
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400

    def test_detail_payload_structure(self):
        exc = _build(404, "gone", "GONE")
        assert exc.detail["detail"] == "gone"
        assert exc.detail["error_code"] == "GONE"
        assert exc.detail["status"] == 404


class TestNotFound:
    def test_without_id(self):
        exc = not_found("Target")
        assert exc.status_code == 404
        assert "Target not found" in exc.detail["detail"]
        assert exc.detail["error_code"] == "NOT_FOUND"

    def test_with_id(self):
        exc = not_found("Target", "abc-123")
        assert "'abc-123'" in exc.detail["detail"]


class TestForbidden:
    def test_default_message(self):
        exc = forbidden()
        assert exc.status_code == 403
        assert exc.detail["error_code"] == "FORBIDDEN"
        assert "Not authorized" in exc.detail["detail"]

    def test_custom_message(self):
        exc = forbidden("Custom denial")
        assert "Custom denial" in exc.detail["detail"]


class TestBadRequest:
    def test_default_error_code(self):
        exc = bad_request("invalid")
        assert exc.status_code == 400
        assert exc.detail["error_code"] == "BAD_REQUEST"

    def test_custom_error_code(self):
        exc = bad_request("nope", error_code="VALIDATION_FAILED")
        assert exc.detail["error_code"] == "VALIDATION_FAILED"


class TestConflict:
    def test_default_error_code(self):
        exc = conflict("already exists")
        assert exc.status_code == 409
        assert exc.detail["error_code"] == "CONFLICT"

    def test_custom_error_code(self):
        exc = conflict("dup", error_code="DUPLICATE")
        assert exc.detail["error_code"] == "DUPLICATE"


class TestUnauthorized:
    def test_default_message(self):
        exc = unauthorized()
        assert exc.status_code == 401
        assert exc.detail["error_code"] == "UNAUTHORIZED"

    def test_custom_message(self):
        exc = unauthorized("Token expired")
        assert "Token expired" in exc.detail["detail"]


class TestRateLimited:
    def test_default(self):
        exc = rate_limited()
        assert exc.status_code == 429
        assert exc.detail["error_code"] == "RATE_LIMITED"
        assert exc.headers is None

    def test_with_retry_after(self):
        exc = rate_limited(retry_after=60)
        assert exc.headers == {"Retry-After": "60"}

    def test_custom_message(self):
        exc = rate_limited("Slow down please")
        assert "Slow down" in exc.detail["detail"]


class TestInternalError:
    def test_default(self):
        exc = internal_error()
        assert exc.status_code == 500
        assert exc.detail["error_code"] == "INTERNAL_ERROR"

    def test_custom_message(self):
        exc = internal_error("DB exploded")
        assert "DB exploded" in exc.detail["detail"]
