"""Unit tests for log redaction via SensitiveFieldFilter."""

from __future__ import annotations

import logging

from app.bootstrap.logging_config import SensitiveFieldFilter, configure_logging


class TestSensitiveFieldFilter:
    """SensitiveFieldFilter redacts sensitive values from log records."""

    def _make_record(self, msg: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=None,
            exc_info=None,
        )

    def setup_method(self):
        self.f = SensitiveFieldFilter()

    def test_redacts_password(self):
        rec = self._make_record("password=supersecret123")
        self.f.filter(rec)
        assert "supersecret123" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_redacts_passwd(self):
        rec = self._make_record("PASSWD: hunter2")
        self.f.filter(rec)
        assert "hunter2" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_redacts_pwd(self):
        rec = self._make_record("pwd=s3cretValue")
        self.f.filter(rec)
        assert "s3cretValue" not in rec.msg

    def test_redacts_token(self):
        rec = self._make_record("tREDACTED_SECRET_60f3b74c18ae
        self.f.filter(rec)
        assert "abc123def456" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_redacts_api_key(self):
        rec = self._make_record("api_key=my-secret-key")
        self.f.filter(rec)
        assert "my-secret-key" not in rec.msg

    def test_redacts_authorization(self):
        rec = self._make_record("authorization=sk-12345")
        self.f.filter(rec)
        assert "sk-12345" not in rec.msg

    def test_redacts_bearer_token(self):
        rec = self._make_record("Bearer eyJhbGciOiJub25lIn0.payload.sig")
        self.f.filter(rec)
        assert "eyJhbGciOiJub25lIn0" not in rec.msg
        assert "Bearer" in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_preserves_normal_message(self):
        rec = self._make_record("Starting server on port 8080")
        self.f.filter(rec)
        assert rec.msg == "Starting server on port 8080"

    def test_preserves_non_string_msg(self):
        rec = self._make_record("ignored")
        rec.msg = 42  # type: ignore[assignment]
        result = self.f.filter(rec)
        assert result is True
        assert rec.msg == 42

    def test_filter_always_returns_true(self):
        rec = self._make_record("password=secret")
        assert self.f.filter(rec) is True

    def test_redacts_json_formatted_message(self):
        rec = self._make_record('{"user": "admin", "password": "s3cret", "action": "login"}')
        self.f.filter(rec)
        assert "s3cret" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_non_string_messages_pass_through(self):
        rec = self._make_record("ignored")
        rec.msg = 12345  # type: ignore[assignment]
        result = self.f.filter(rec)
        assert result is True
        assert rec.msg == 12345

    def test_non_string_dict_message(self):
        rec = self._make_record("ignored")
        rec.msg = {"key": "value"}  # type: ignore[assignment]
        result = self.f.filter(rec)
        assert result is True
        assert rec.msg == {"key": "value"}

    def test_mixed_content_password_in_middle(self):
        rec = self._make_record("User login attempt password=hunter2 from 10.0.0.1")
        self.f.filter(rec)
        assert "hunter2" not in rec.msg
        assert "***REDACTED***" in rec.msg
        assert "User login attempt" in rec.msg
        assert "10.0.0.1" in rec.msg

    def test_case_insensitive_PASSWORD(self):
        rec = self._make_record("PASSWORD=SuperSecret")
        self.f.filter(rec)
        assert "SuperSecret" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_case_insensitive_Password(self):
        rec = self._make_record("Password=MixedCase123")
        self.f.filter(rec)
        assert "MixedCase123" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_case_insensitive_TOKEN(self):
        rec = self._make_record("TOKEN=abc-xyz-123")
        self.f.filter(rec)
        assert "abc-xyz-123" not in rec.msg
        assert "***REDACTED***" in rec.msg

    def test_multiple_sensitive_fields_in_one_message(self):
        rec = self._make_record("password=secret1 token=secret2")
        self.f.filter(rec)
        assert "secret1" not in rec.msg
        assert "secret2" not in rec.msg


class TestFilterAppliedToHandlers:
    """SensitiveFieldFilter is wired into the logging configuration."""

    def test_configure_logging_adds_sensitive_filter(self):
        configure_logging(log_format="text", log_level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) > 0
        handler = root.handlers[0]
        filter_types = [type(f) for f in handler.filters]
        assert SensitiveFieldFilter in filter_types
