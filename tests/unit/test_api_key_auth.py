"""Unit tests for API key authentication (app/api/dependencies.py — _authenticate_api_key)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.dependencies import _authenticate_api_key, get_current_user_from_token_or_api_key


def _make_api_key(
    *,
    raw_key: str = "abcdefgh_rest_of_key_here",
    is_active: bool = True,
    expires_at: datetime | None = None,
    user_id: str = "u-1",
) -> tuple[str, MagicMock]:
    """Return (raw_key, mock_api_key_row)."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:8]

    api_key = MagicMock()
    api_key.key_hash = key_hash
    api_key.key_prefix = prefix
    api_key.is_active = is_active
    api_key.expires_at = expires_at
    api_key.user_id = user_id
    api_key.last_used_at = None
    return raw_key, api_key


def _make_user(*, user_id: str = "u-1", is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.is_active = is_active
    user.username = "testuser"
    return user


def _session_returning(api_key_row, user_row=None):
    """Build an AsyncMock session that returns api_key_row then user_row from execute()."""
    session = AsyncMock()

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = api_key_row
        else:
            result.scalar_one_or_none.return_value = user_row
        return result

    session.execute = _execute
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
class TestAuthenticateApiKey:
    async def test_valid_key_returns_user(self):
        raw_key, api_key_row = _make_api_key()
        user = _make_user()
        session = _session_returning(api_key_row, user)

        result = await _authenticate_api_key(raw_key, session)

        assert result.id == "u-1"

    async def test_valid_key_updates_last_used(self):
        raw_key, api_key_row = _make_api_key()
        user = _make_user()
        session = _session_returning(api_key_row, user)

        await _authenticate_api_key(raw_key, session)

        assert api_key_row.last_used_at is not None
        session.commit.assert_awaited()

    async def test_expired_key_rejected(self):
        raw_key, api_key_row = _make_api_key(
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session = _session_returning(api_key_row)

        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_key(raw_key, session)
        assert exc_info.value.status_code == 401

    async def test_inactive_key_rejected(self):
        """An inactive key should not even match the query (is_active filter),
        so the result comes back None."""
        raw_key = "abcdefgh_rest_of_key_here"
        session = _session_returning(None)  # no match

        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_key(raw_key, session)
        assert exc_info.value.status_code == 401

    async def test_wrong_hash_rejected(self):
        raw_key, api_key_row = _make_api_key()
        # Tamper with stored hash
        api_key_row.key_hash = "badhash"
        session = _session_returning(api_key_row)

        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_key(raw_key, session)
        assert exc_info.value.status_code == 401

    async def test_inactive_user_rejected(self):
        raw_key, api_key_row = _make_api_key()
        user = _make_user(is_active=False)
        session = _session_returning(api_key_row, user)

        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_key(raw_key, session)
        assert exc_info.value.status_code == 401

    async def test_no_user_found_rejected(self):
        raw_key, api_key_row = _make_api_key()
        session = _session_returning(api_key_row, None)

        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_key(raw_key, session)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
class TestTokenOrApiKeyDispatch:
    async def test_api_key_header_dispatches_to_api_key_auth(self):
        raw_key, api_key_row = _make_api_key()
        user = _make_user()
        session = _session_returning(api_key_row, user)

        request = MagicMock()
        request.headers = {"X-API-Key": raw_key}

        result = await get_current_user_from_token_or_api_key(request, session=session)
        assert result.id == "u-1"

    async def test_no_auth_raises_401(self):
        session = AsyncMock()
        request = MagicMock()
        request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_from_token_or_api_key(request, session=session)
        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail
