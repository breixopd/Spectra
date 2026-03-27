"""Tests for security features: lockout, token blacklist, websocket auth, settings RBAC."""

from datetime import datetime, timedelta, timezone
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError as JWTError

from app.api.routers.auth import (
    LOCKOUT_THRESHOLD_1,
    LOCKOUT_THRESHOLD_2,
    _check_lockout,
    _record_failure,
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


@pytest.fixture(autouse=True)
def _clear_blacklist():
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()


class TestTokenBlacklist:
    def test_invalidate_token_blocks_decode(self):
        token = create_access_token(data={"sub": "testuser"})
        payload = decode_token(token)
        assert payload["sub"] == "testuser"

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
        assert is_token_blacklisted(token) is False

        time.sleep(0.1)
        invalidate_all_user_tokens("victimuser")

        assert is_token_blacklisted(token) is True
        with pytest.raises(JWTError, match="revoked"):
            decode_token(token)

    def test_new_token_after_user_invalidation_works(self):
        invalidate_all_user_tokens("someuser")
        time.sleep(1.1)
        new_token = create_access_token(data={"sub": "someuser"})
        assert is_token_blacklisted(new_token) is False
        payload = decode_token(new_token)
        assert payload["sub"] == "someuser"


class TestAccountLockout:
    def _make_user(self, fail_count=0, locked_until=None):
        user = MagicMock()
        user.login_fail_count = fail_count
        user.locked_until = locked_until
        return user

    @pytest.mark.asyncio
    async def test_no_lockout_initially(self):
        user = self._make_user()
        await _check_lockout(user)

    @pytest.mark.asyncio
    async def test_lockout_after_threshold_1(self):
        user = self._make_user(fail_count=LOCKOUT_THRESHOLD_1 - 1)
        session = AsyncMock()
        await _record_failure(user, session)

        with pytest.raises(HTTPException) as exc_info:
            await _check_lockout(user)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_lockout_after_threshold_2(self):
        user = self._make_user(fail_count=LOCKOUT_THRESHOLD_2 - 1)
        session = AsyncMock()
        await _record_failure(user, session)

        with pytest.raises(HTTPException) as exc_info:
            await _check_lockout(user)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_lockout_expires(self):
        user = self._make_user(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        await _check_lockout(user)


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


class TestSettingsRBAC:
    def test_settings_endpoint_has_superuser_dependency(self):
        import inspect

        from app.api.routers.ui import update_settings

        sig = inspect.signature(update_settings)
        param_names = list(sig.parameters.keys())
        assert "_current_user" in param_names


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
