"""Tests for logging configuration (app/core/logging_config.py)."""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.core.logging_config import (
    CorrelationIdMiddleware,
    HumanFormatter,
    JSONFormatter,
    SensitiveFieldFilter,
    _CorrelationFilter,
    configure_logging,
    correlation_id_var,
    get_correlation_id,
)


class TestCorrelationId:
    """Tests for correlation ID context variable."""

    def test_default_is_none(self):
        assert get_correlation_id() is None

    def test_set_and_get(self):
        token = correlation_id_var.set("test-cid-123")
        try:
            assert get_correlation_id() == "test-cid-123"
        finally:
            correlation_id_var.reset(token)

    def test_reset_restores_default(self):
        token = correlation_id_var.set("temp")
        correlation_id_var.reset(token)
        assert get_correlation_id() is None


class TestCorrelationFilter:
    """Tests for the _CorrelationFilter log filter."""

    def test_injects_correlation_id_into_record(self):
        filt = _CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        token = correlation_id_var.set("filter-cid")
        try:
            result = filt.filter(record)
            assert result is True
            assert record.correlation_id == "filter-cid"  # type: ignore[attr-defined]
        finally:
            correlation_id_var.reset(token)

    def test_empty_string_when_no_correlation_id(self):
        filt = _CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert record.correlation_id == ""  # type: ignore[attr-defined]

    def test_shutdown_safe_when_import_system_is_gone(self):
        filt = _CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with patch.object(sys, "meta_path", None):
            assert filt.filter(record) is True
        assert record.correlation_id == ""  # type: ignore[attr-defined]


class TestSensitiveFieldFilter:
    """Tests for shutdown-safe sensitive data redaction."""

    def test_redacts_sensitive_fields(self):
        filt = SensitiveFieldFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="password=secret token=abc",
            args=(),
            exc_info=None,
        )
        assert filt.filter(record) is True
        assert "secret" not in record.msg
        assert "abc" not in record.msg

    def test_shutdown_safe_when_import_system_is_gone(self):
        filt = SensitiveFieldFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="password=secret",
            args=(),
            exc_info=None,
        )
        with patch.object(sys, "meta_path", None):
            assert filt.filter(record) is True


class TestJSONFormatter:
    """Tests for JSONFormatter output."""

    def _make_record(self, msg="test message", level=logging.INFO, cid=""):
        record = logging.LogRecord(
            name="spectra.test",
            level=level,
            pathname="test.py",
            lineno=42,
            msg=msg,
            args=(),
            exc_info=None,
        )
        record.correlation_id = cid  # type: ignore[attr-defined]
        return record

    def test_output_is_valid_json(self):
        fmt = JSONFormatter()
        record = self._make_record()
        output = fmt.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_contains_required_fields(self):
        fmt = JSONFormatter()
        record = self._make_record("hello world", cid="cid-99")
        parsed = json.loads(fmt.format(record))

        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "spectra.test"
        assert parsed["correlation_id"] == "cid-99"
        assert "timestamp" in parsed

    def test_includes_exception_info(self):
        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="error",
                args=(),
                exc_info=sys.exc_info(),
            )
            record.correlation_id = ""  # type: ignore[attr-defined]

        output = json.loads(fmt.format(record))
        assert "exception" in output
        assert "ValueError" in output["exception"]


class TestHumanFormatter:
    """Tests for the HumanFormatter."""

    def _make_record(self, msg="test", cid=""):
        record = logging.LogRecord(
            name="spectra.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        record.correlation_id = cid  # type: ignore[attr-defined]
        return record

    def test_output_without_correlation_id(self):
        fmt = HumanFormatter()
        record = self._make_record("plain log")
        output = fmt.format(record)
        assert "plain log" in output
        assert "spectra.test" in output

    def test_output_with_correlation_id(self):
        fmt = HumanFormatter()
        record = self._make_record("traced log", cid="cid-xyz")
        output = fmt.format(record)
        assert "[cid-xyz]" in output
        assert "traced log" in output
        assert record.msg == "traced log"


class TestConfigureLogging:
    """Tests for the configure_logging() factory function."""

    def test_text_format_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOG_FORMAT", None)
            configure_logging()

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        handler = root.handlers[-1]
        assert isinstance(handler.formatter, HumanFormatter)

    def test_json_format_via_env(self):
        with patch.dict(os.environ, {"LOG_FORMAT": "json"}):
            configure_logging()

        root = logging.getLogger()
        handler = root.handlers[-1]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_sets_info_level(self):
        configure_logging(log_level="INFO")
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestCorrelationIdMiddleware:
    """Tests for the CorrelationIdMiddleware."""

    @pytest.mark.asyncio
    async def test_generates_correlation_id_when_absent(self):
        app = MagicMock()
        mw = CorrelationIdMiddleware(app)

        request = MagicMock()
        request.headers = {}

        captured_cid = None

        async def fake_next(req):
            nonlocal captured_cid
            captured_cid = get_correlation_id()
            resp = MagicMock()
            resp.headers = {}
            return resp

        response = await mw.dispatch(request, fake_next)
        assert captured_cid is not None
        assert len(captured_cid) > 0
        # Should be set in response header
        assert response.headers[CorrelationIdMiddleware.HEADER] == captured_cid

    @pytest.mark.asyncio
    async def test_uses_existing_correlation_id_from_header(self):
        app = MagicMock()
        mw = CorrelationIdMiddleware(app)

        request = MagicMock()
        request.headers = {"X-Correlation-ID": "existing-cid-42"}

        captured_cid = None

        async def fake_next(req):
            nonlocal captured_cid
            captured_cid = get_correlation_id()
            resp = MagicMock()
            resp.headers = {}
            return resp

        await mw.dispatch(request, fake_next)
        assert captured_cid == "existing-cid-42"

    @pytest.mark.asyncio
    async def test_resets_context_after_request(self):
        app = MagicMock()
        mw = CorrelationIdMiddleware(app)

        request = MagicMock()
        request.headers = {"X-Correlation-ID": "temp-cid"}

        async def fake_next(req):
            resp = MagicMock()
            resp.headers = {}
            return resp

        await mw.dispatch(request, fake_next)
        # After dispatch, the context var should be reset
        assert get_correlation_id() is None
