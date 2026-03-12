"""Tests for security features: lockout, token blacklist, websocket auth, settings RBAC."""

import time
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from jose import JWTError

from app.api.routers.auth import (
    LOCKOUT_THRESHOLD_1,
    LOCKOUT_THRESHOLD_2,
    _check_lockout,
    _lockout_lock,
    _login_failures,
    _record_failure,
    _reset_failures,
)
from app.core.security import (
    _blacklist_lock,
    _blacklisted_tokens,
    _user_token_blacklist,
    create_access_token,
    decode_token,
    invalidate_all_user_tokens,
    invalidate_token,
    is_token_blacklisted,
)
from app.core.websocket import ConnectionManager

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _clear_blacklist():
    """Clear token blacklist state before each test."""
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()


@pytest.fixture(autouse=True)
def _clear_lockout():
    """Clear lockout state before each test."""
    with _lockout_lock:
        _login_failures.clear()
    yield
    with _lockout_lock:
        _login_failures.clear()


# --- Token Blacklist Tests ---


class TestTokenBlacklist:
    def test_invalidate_token_blocks_decode(self):
        token = create_access_token(data={"sub": "testuser"})
        # Token is valid before blacklisting
        payload = decode_token(token)
        assert payload["sub"] == "testuser"

        # Blacklist and verify it throws
        invalidate_token(token)
        assert is_token_blacklisted(token) is True
        with pytest.raises(JWTError, match="revoked"):
            decode_token(token)

    def test_non_blacklisted_token_works(self):
        token = create_access_token(data={"sub": "testuser"})
        assert is_token_blacklisted(token) is False
        payload = decode_token(token)
        assert payload["sub"] == "testuser"

    def test_invalidate_all_user_tokens(self):
        token = create_access_token(data={"sub": "victimuser"})
        # Valid before invalidation
        assert is_token_blacklisted(token) is False

        time.sleep(0.1)  # Ensure timestamp difference
        invalidate_all_user_tokens("victimuser")

        assert is_token_blacklisted(token) is True
        with pytest.raises(JWTError, match="revoked"):
            decode_token(token)

    def test_new_token_after_user_invalidation_works(self):
        invalidate_all_user_tokens("someuser")
        time.sleep(1.1)  # Must exceed +1s boundary used by invalidation
        new_token = create_access_token(data={"sub": "someuser"})
        assert is_token_blacklisted(new_token) is False
        payload = decode_token(new_token)
        assert payload["sub"] == "someuser"


# --- Account Lockout Tests ---


class TestAccountLockout:
    def test_no_lockout_initially(self):
        # Should not raise
        _check_lockout("192.168.1.1")

    def test_lockout_after_threshold_1(self):
        ip = "10.0.0.1"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        with pytest.raises(HTTPException) as exc_info:
            _check_lockout(ip)
        assert exc_info.value.status_code == 429

    def test_lockout_after_threshold_2(self):
        ip = "10.0.0.2"
        for _ in range(LOCKOUT_THRESHOLD_2):
            _record_failure(ip)

        with pytest.raises(HTTPException) as exc_info:
            _check_lockout(ip)
        assert exc_info.value.status_code == 429

    def test_reset_clears_lockout(self):
        ip = "10.0.0.3"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        # Locked
        with pytest.raises(HTTPException):
            _check_lockout(ip)

        # Reset
        _reset_failures(ip)
        # Should not raise after reset
        _check_lockout(ip)

    def test_lockout_expires(self):
        ip = "10.0.0.4"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        # Manually set locked_until to the past
        with _lockout_lock:
            _login_failures[ip]["locked_until"] = time.time() - 1

        # Should not raise — lockout expired
        _check_lockout(ip)


# --- WebSocket Auth Tests ---


class TestWebSocketAuth:
    @pytest.mark.asyncio
    async def test_reject_without_token(self):
        manager = ConnectionManager()
        ws = AsyncMock()
        ws.query_params = {}

        result = await manager.connect(ws, require_auth=True)
        assert result is False
        ws.close.assert_awaited_once_with(code=4001, reason="Authentication required")

    @pytest.mark.asyncio
    async def test_reject_with_invalid_token(self):
        manager = ConnectionManager()
        ws = AsyncMock()
        ws.query_params = {"token": "invalid.jwt.token"}

        result = await manager.connect(ws, require_auth=True)
        assert result is False
        ws.close.assert_awaited_once()
        assert ws.close.call_args[1]["code"] == 4001

    @pytest.mark.asyncio
    async def test_accept_with_valid_token(self):
        manager = ConnectionManager()
        token = create_access_token(data={"sub": "testuser"})
        ws = AsyncMock()
        ws.query_params = {"token": token}

        result = await manager.connect(ws, require_auth=True)
        assert result is True
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_accept_without_auth_requirement(self):
        manager = ConnectionManager()
        ws = AsyncMock()
        ws.query_params = {}

        result = await manager.connect(ws, require_auth=False)
        assert result is True
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_blacklisted_token(self):
        manager = ConnectionManager()
        token = create_access_token(data={"sub": "testuser"})
        invalidate_token(token)

        ws = AsyncMock()
        ws.query_params = {"token": token}

        result = await manager.connect(ws, require_auth=True)
        assert result is False
        ws.close.assert_awaited_once()


# --- Settings RBAC Tests ---


class TestSettingsRBAC:
    def test_settings_endpoint_has_superuser_dependency(self):
        """Verify the settings POST endpoint requires superuser auth."""
        import inspect

        from app.api.routers.ui import update_settings

        sig = inspect.signature(update_settings)
        param_names = list(sig.parameters.keys())
        # Should have _current_user parameter (the superuser dep)
        assert "_current_user" in param_names


# --- RAG Functional Guard Tests ---


class TestRAGFunctionalGuard:
    def test_embedding_service_is_functional_false_on_fallback(self):
        from app.services.ai.embeddings import EmbeddingService

        svc = EmbeddingService()
        svc._use_fallback = True
        assert svc.is_functional is False

    def test_embedding_service_is_functional_false_no_model(self):
        from app.services.ai.embeddings import EmbeddingService

        svc = EmbeddingService()
        assert svc.is_functional is False

    def test_rag_service_is_functional_false(self):
        from app.services.ai.rag import RAGService

        svc = RAGService()
        svc.embeddings._use_fallback = True
        svc.embeddings._api_ready = False
        assert svc.is_functional is False

    @pytest.mark.asyncio
    async def test_rag_search_returns_empty_on_fallback(self):
        from app.services.ai.rag import RAGService

        svc = RAGService()
        svc.embeddings._use_fallback = True
        svc._table_ready = True
        results = await svc.search("test query")
        assert results == []


# --- Audit Log Model Tests ---


class TestAuditLogModel:
    def test_audit_event_type_values(self):
        from app.models.audit_log import AuditEventType

        assert AuditEventType.LOGIN.value == "LOGIN"
        assert AuditEventType.LOGOUT.value == "LOGOUT"
        assert AuditEventType.SETTINGS_CHANGED.value == "SETTINGS_CHANGED"
        assert AuditEventType.TOKEN_REVOKED.value == "TOKEN_REVOKED"

    def test_audit_log_model_tablename(self):
        from app.models.audit_log import AuditLog

        assert AuditLog.__tablename__ == "audit_logs"
