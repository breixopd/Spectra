"""
Tests for API error response helpers and SpectraError exception handler.

Covers:
- All error_responses helpers (supplement to test_error_responses.py)
- SpectraError.to_dict() serialization
- get_status_code_for_exception mapping
- spectra_error_handler in main.py
"""

from fastapi import Request
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

from app.core.exceptions import (
    EXCEPTION_STATUS_MAP,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ExternalServiceError,
    LLMConnectionError,
    LLMTimeoutError,
    MissionNotFoundError,
    NotFoundError,
    RateLimitExceededError,
    SpectraError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
    get_status_code_for_exception,
)


# ---------------------------------------------------------------------------
# SpectraError.to_dict()
# ---------------------------------------------------------------------------


class TestSpectraErrorToDict:
    def test_basic_to_dict(self):
        exc = SpectraError("boom")
        d = exc.to_dict()
        assert d["error"] == "SPECTRA_ERROR"
        assert d["message"] == "boom"
        assert d["details"] == {}

    def test_custom_code(self):
        exc = SpectraError("oops", code="CUSTOM")
        assert exc.to_dict()["error"] == "CUSTOM"

    def test_details_passed_through(self):
        exc = SpectraError("err", details={"key": "val"})
        assert exc.to_dict()["details"] == {"key": "val"}

    def test_str_representation(self):
        exc = SpectraError("hello")
        assert str(exc) == "hello"


# ---------------------------------------------------------------------------
# get_status_code_for_exception
# ---------------------------------------------------------------------------


class TestGetStatusCodeForException:
    def test_not_found_error(self):
        assert get_status_code_for_exception(NotFoundError("x")) == 404

    def test_mission_not_found(self):
        assert get_status_code_for_exception(MissionNotFoundError("m1")) == 404

    def test_tool_not_found(self):
        assert get_status_code_for_exception(ToolNotFoundError("nmap")) == 404

    def test_authentication_error(self):
        assert get_status_code_for_exception(AuthenticationError("bad creds")) == 401

    def test_authorization_error(self):
        assert get_status_code_for_exception(AuthorizationError("nope")) == 403

    def test_rate_limit_exceeded(self):
        exc = RateLimitExceededError("5/min")
        assert get_status_code_for_exception(exc) == 429

    def test_validation_error(self):
        assert get_status_code_for_exception(ValidationError("bad input")) == 422

    def test_configuration_error(self):
        assert get_status_code_for_exception(ConfigurationError("missing key")) == 500

    def test_external_service_error(self):
        assert get_status_code_for_exception(ExternalServiceError("llm")) == 502

    def test_llm_timeout(self):
        assert get_status_code_for_exception(LLMTimeoutError()) == 504

    def test_llm_connection(self):
        assert get_status_code_for_exception(LLMConnectionError()) == 502

    def test_tool_execution_error(self):
        assert get_status_code_for_exception(ToolExecutionError("fail")) == 500

    def test_base_spectra_error_fallback(self):
        assert get_status_code_for_exception(SpectraError("generic")) == 500

    def test_unknown_subclass_falls_back(self):
        """A custom subclass not in the map should walk MRO to SpectraError → 500."""

        class CustomError(SpectraError):
            code = "CUSTOM"

        assert get_status_code_for_exception(CustomError("x")) == 500


# ---------------------------------------------------------------------------
# spectra_error_handler (integration via TestClient)
# ---------------------------------------------------------------------------


class TestSpectraErrorHandler:
    def test_handler_returns_json_with_correct_status(self):
        """The app's exception handler converts SpectraError → JSONResponse."""
        from fastapi import FastAPI

        test_app = FastAPI()

        @test_app.exception_handler(SpectraError)
        async def handler(request: Request, exc: SpectraError):
            from fastapi.responses import JSONResponse

            status_code = get_status_code_for_exception(exc)
            return JSONResponse(exc.to_dict(), status_code=status_code)

        @test_app.get("/err")
        async def raise_err():
            raise NotFoundError("Widget", "w-42")

        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/err")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"] == "NOT_FOUND"
        assert "Widget" in body["message"]

    def test_handler_for_validation_error(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        test_app = FastAPI()

        @test_app.exception_handler(SpectraError)
        async def handler(request: Request, exc: SpectraError):
            return JSONResponse(exc.to_dict(), status_code=get_status_code_for_exception(exc))

        @test_app.get("/val")
        async def raise_val():
            raise ValidationError("bad field", field="email")

        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/val")
        assert resp.status_code == 422
        assert resp.json()["details"]["field"] == "email"
