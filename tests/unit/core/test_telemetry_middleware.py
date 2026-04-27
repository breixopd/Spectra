"""Tests for TelemetryMiddleware (app/core/telemetry_middleware.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.telemetry.telemetry_middleware import TelemetryMiddleware, _normalize_path


class TestNormalizePath:
    """Tests for the _normalize_path helper."""

    def test_replaces_uuid(self):
        path = "/api/missions/550e8400-e29b-41d4-a716-446655440000/status"
        assert _normalize_path(path) == "/api/missions/{id}/status"

    def test_replaces_integer_id(self):
        assert _normalize_path("/api/targets/42") == "/api/targets/{id}"

    def test_replaces_hex_id(self):
        assert _normalize_path("/api/findings/abc123def456") == "/api/findings/{id}"

    def test_no_replacement_for_short_hex(self):
        # Hex shorter than 6 chars should not be treated as ID
        assert _normalize_path("/api/items/abc") == "/api/items/abc"

    def test_preserves_static_path(self):
        assert _normalize_path("/api/health") == "/api/health"

    def test_replaces_multiple_ids(self):
        path = "/api/missions/550e8400-e29b-41d4-a716-446655440000/findings/99"
        assert _normalize_path(path) == "/api/missions/{id}/findings/{id}"


class TestTelemetryMiddleware:
    """Tests for the TelemetryMiddleware dispatch logic."""

    @pytest.fixture
    def middleware(self):
        app = MagicMock()
        return TelemetryMiddleware(app)

    def _make_request(self, path: str = "/api/test", method: str = "GET"):
        request = MagicMock()
        request.url.path = path
        request.method = method
        return request

    @pytest.mark.asyncio
    async def test_static_path_skipped(self, middleware):
        """Static asset requests should bypass telemetry."""
        request = self._make_request("/static/css/style.css")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel:
            await middleware.dispatch(request, call_next)
            mock_tel.increment_counter.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_counting(self, middleware):
        """Successful requests increment the total counter."""
        request = self._make_request("/api/missions")
        response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=response)

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        # Should have: active+1, active-1, total
        total_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.total"]
        assert len(total_calls) == 1
        total_calls[0].args[2] if len(total_calls[0].args) > 2 else total_calls[0].kwargs.get("labels", {})
        # Check via the positional args pattern: increment_counter(name, value, labels)
        call_a = total_calls[0]
        assert call_a[0][0] == "http.requests.total"

    @pytest.mark.asyncio
    async def test_latency_recorded(self, middleware):
        """Request latency should be recorded as a histogram."""
        request = self._make_request("/api/findings")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            await middleware.dispatch(request, call_next)

        histogram_calls = [
            c for c in mock_tel.observe_histogram.call_args_list if c.args[0] == "http.request.duration_ms"
        ]
        assert len(histogram_calls) == 1
        # Duration should be a positive float
        assert histogram_calls[0].args[1] >= 0

    @pytest.mark.asyncio
    async def test_error_counting_5xx(self, middleware):
        """5xx responses should increment the error counter."""
        request = self._make_request("/api/fail")
        call_next = AsyncMock(return_value=MagicMock(status_code=500))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            await middleware.dispatch(request, call_next)

        error_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.errors"]
        assert len(error_calls) == 1

    @pytest.mark.asyncio
    async def test_no_error_counting_4xx(self, middleware):
        """4xx responses should NOT increment the error counter."""
        request = self._make_request("/api/missing")
        call_next = AsyncMock(return_value=MagicMock(status_code=404))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            await middleware.dispatch(request, call_next)

        error_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.errors"]
        assert len(error_calls) == 0

    @pytest.mark.asyncio
    async def test_exception_records_error(self, middleware):
        """Unhandled exceptions should record error metrics and re-raise."""
        request = self._make_request("/api/boom")
        call_next = AsyncMock(side_effect=RuntimeError("kaboom"))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="kaboom"):
                await middleware.dispatch(request, call_next)

        error_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.errors"]
        assert len(error_calls) == 1

    @pytest.mark.asyncio
    async def test_active_request_gauge(self, middleware):
        """Active requests gauge should increment and decrement around call_next."""
        request = self._make_request("/api/work")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            await middleware.dispatch(request, call_next)

        active_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.active"]
        # Should have +1 then -1
        assert len(active_calls) == 2

    @pytest.mark.asyncio
    async def test_path_normalization_in_labels(self, middleware):
        """Labels should use normalized path (IDs replaced)."""
        request = self._make_request("/api/missions/550e8400-e29b-41d4-a716-446655440000")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value=None),
        ):
            await middleware.dispatch(request, call_next)

        total_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.total"]
        assert len(total_calls) == 1
        labels = total_calls[0][0][2]  # third positional arg
        assert labels["path_template"] == "/api/missions/{id}"

    @pytest.mark.asyncio
    async def test_correlation_id_in_labels(self, middleware):
        """Correlation ID should appear in labels when present."""
        request = self._make_request("/api/data")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch("app.telemetry.telemetry_middleware.telemetry") as mock_tel,
            patch("app.telemetry.telemetry_middleware.get_correlation_id", return_value="req-abc-123"),
        ):
            await middleware.dispatch(request, call_next)

        total_calls = [c for c in mock_tel.increment_counter.call_args_list if c.args[0] == "http.requests.total"]
        labels = total_calls[0][0][2]
        assert labels["correlation_id"] == "req-abc-123"
