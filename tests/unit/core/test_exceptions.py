"""Tests for app.auth.exceptions module."""

from app.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CircuitBreakerOpenError,
    LLMConnectionError,
    LLMError,
    LLMResponseError,
    MissionCancelledError,
    MissionNotFoundError,
    MissionStateError,
    NotFoundError,
    PluginInstallationError,
    RateLimitError,
    ServiceUnavailableError,
    SpectraError,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolNotFoundError,
    ToolTimeoutError,
    ValidationError,
    get_status_code_for_exception,
)


class TestSpectraErrorBase:
    def test_default_code(self):
        err = SpectraError("boom")
        assert err.code == "SPECTRA_ERROR"
        assert err.message == "boom"
        assert err.details == {}

    def test_custom_code(self):
        err = SpectraError("boom", code="CUSTOM")
        assert err.code == "CUSTOM"

    def test_details_passed_through(self):
        err = SpectraError("boom", details={"key": "val"})
        assert err.details == {"key": "val"}

    def test_to_dict(self):
        err = SpectraError("boom", code="TEST", details={"x": 1})
        d = err.to_dict()
        assert d == {"error": "TEST", "message": "boom", "details": {"x": 1}}

    def test_str_representation(self):
        err = SpectraError("something went wrong")
        assert str(err) == "something went wrong"


class TestLLMErrors:
    def test_llm_connection_error(self):
        err = LLMConnectionError(host="localhost:11434")
        assert err.code == "LLM_CONNECTION_ERROR"
        assert err.details["host"] == "localhost:11434"

    def test_llm_response_error(self):
        err = LLMResponseError("bad response", status_code=500)
        assert err.details["status_code"] == 500

    def test_llm_error_hierarchy(self):
        assert issubclass(LLMError, SpectraError)


class TestToolErrors:
    def test_tool_execution_error(self):
        err = ToolExecutionError("failed", tool_id="nmap", exit_code=1, stderr="err")
        assert err.code == "TOOL_EXECUTION_ERROR"
        assert err.details["tool_id"] == "nmap"
        assert err.details["exit_code"] == 1

    def test_tool_timeout_error(self):
        err = ToolTimeoutError("nmap", 60)
        assert "nmap" in err.message
        assert err.details["timeout_seconds"] == 60

    def test_tool_not_found_error(self):
        err = ToolNotFoundError("fake_tool")
        assert err.code == "TOOL_NOT_FOUND"
        assert err.details["tool_id"] == "fake_tool"

    def test_tool_not_available_error(self):
        err = ToolNotAvailableError("nmap", "installing")
        assert "installing" in err.message
        assert err.details["status"] == "installing"


class TestMissionErrors:
    def test_mission_not_found(self):
        err = MissionNotFoundError("abc123")
        assert err.details["mission_id"] == "abc123"
        assert err.code == "MISSION_NOT_FOUND"

    def test_mission_state_error(self):
        err = MissionStateError("abc", "running", "planning")
        assert err.details["current_state"] == "running"
        assert err.details["attempted_state"] == "planning"

    def test_mission_cancelled(self):
        err = MissionCancelledError("xyz")
        assert err.details["mission_id"] == "xyz"


class TestOtherErrors:
    def test_plugin_installation_error(self):
        err = PluginInstallationError("nmap", "checksum mismatch")
        assert err.details["plugin_id"] == "nmap"
        assert err.details["reason"] == "checksum mismatch"

    def test_rate_limit_error(self):
        err = RateLimitError("100/hour", retry_after=60)
        assert err.details["retry_after_seconds"] == 60

    def test_validation_error(self):
        err = ValidationError("bad input", field="name")
        assert err.details["field"] == "name"

    def test_not_found_error_with_identifier(self):
        err = NotFoundError("User", "42")
        assert err.message == "User not found: 42"

    def test_not_found_error_without_identifier(self):
        err = NotFoundError("User")
        assert err.message == "User not found"

    def test_circuit_breaker_open(self):
        err = CircuitBreakerOpenError("llm", 30)
        assert err.details["recovery_seconds"] == 30

    def test_service_unavailable(self):
        err = ServiceUnavailableError("ollama", reason="down")
        assert err.details["service"] == "ollama"


class TestGetStatusCodeForException:
    def test_not_found_returns_404(self):
        assert get_status_code_for_exception(NotFoundError("x")) == 404

    def test_mission_not_found_returns_404(self):
        assert get_status_code_for_exception(MissionNotFoundError("x")) == 404

    def test_authentication_returns_401(self):
        assert get_status_code_for_exception(AuthenticationError("x")) == 401

    def test_authorization_returns_403(self):
        assert get_status_code_for_exception(AuthorizationError("x")) == 403

    def test_rate_limit_returns_429(self):
        assert get_status_code_for_exception(RateLimitError("x")) == 429

    def test_validation_returns_422(self):
        assert get_status_code_for_exception(ValidationError("x")) == 422

    def test_mission_state_returns_409(self):
        assert get_status_code_for_exception(MissionStateError("a", "b", "c")) == 409

    def test_base_spectra_error_returns_500(self):
        assert get_status_code_for_exception(SpectraError("x")) == 500

    def test_tool_not_found_returns_404(self):
        assert get_status_code_for_exception(ToolNotFoundError("x")) == 404

    def test_circuit_breaker_returns_503(self):
        assert get_status_code_for_exception(CircuitBreakerOpenError("x", 10)) == 503
