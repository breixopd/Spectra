"""Tests for JWT security: token type enforcement, refresh token rejection, cookie flags."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.core.security import (
    _blacklist_lock,
    _blacklisted_tokens,
    _user_token_blacklist,
    create_access_token,
    create_refresh_token,
    decode_token,
    invalidate_all_user_tokens,
)


@pytest.fixture(autouse=True)
def _clear_blacklist():
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()


def _make_request(
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    path: str = "/api/v1/test",
) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope)


def _mock_async_session_maker_with_user(user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx)


# ---------------------------------------------------------------------------
# Token type claims
# ---------------------------------------------------------------------------


def test_access_token_has_type_access():
    token = create_access_token(data={"sub": "testuser"})
    payload = decode_token(token)
    assert payload["type"] == "access"


def test_refresh_token_has_type_refresh():
    token = create_refresh_token(data={"sub": "testuser"})
    payload = decode_token(token)
    assert payload["type"] == "refresh"


# ---------------------------------------------------------------------------
# Refresh tokens rejected for API access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_rejects_refresh_token():
    """get_current_user raises 401 when given a refresh token."""
    from app.api.dependencies import get_current_user

    refresh = create_refresh_token(data={"sub": "testuser"})
    request = _make_request(headers={"authorization": f"Bearer {refresh}"})

    mock_session = AsyncMock()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=request, session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_accepts_access_token():
    """get_current_user accepts a valid access token and fetches the user."""
    from app.api.dependencies import get_current_user

    access = create_access_token(data={"sub": "testuser"})
    request = _make_request(headers={"authorization": f"Bearer {access}"})

    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_user.invalidated_before = None
    mock_user.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("app.api.dependencies.async_session_maker") as session_maker:
        user = await get_current_user(request=request, session=mock_session, token=access)

    assert user.username == "testuser"
    mock_session.execute.assert_awaited_once()
    session_maker.assert_not_called()


@pytest.mark.asyncio
async def test_get_current_user_accepts_cookie_auth_without_bearer_header():
    """get_current_user falls back to the access_token cookie for browser API calls."""
    from app.api.dependencies import get_current_user

    access = create_access_token(data={"sub": "cookieuser"})
    request = _make_request(cookies={"access_token": access})

    mock_user = MagicMock()
    mock_user.username = "cookieuser"
    mock_user.invalidated_before = None
    mock_user.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("app.api.dependencies.async_session_maker") as session_maker:
        user = await get_current_user(request=request, session=mock_session)

    assert user.username == "cookieuser"
    mock_session.execute.assert_awaited_once()
    session_maker.assert_not_called()


# ---------------------------------------------------------------------------
# Token without type claim
# ---------------------------------------------------------------------------


def test_token_without_type_claim_still_decodes():
    """A legacy token without 'type' can still be decoded by decode_token,
    but get_current_user will reject it since type != 'access'."""
    from datetime import UTC, datetime

    import jwt

    from app.core.config import settings

    payload = {
        "sub": "legacyuser",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    decoded = decode_token(token)
    assert "type" not in decoded


@pytest.mark.asyncio
async def test_get_current_user_rejects_token_without_type():
    """get_current_user rejects tokens missing the 'type' claim."""
    from fastapi import HTTPException
    import jwt

    from app.api.dependencies import get_current_user
    from app.core.config import settings

    payload = {
        "sub": "legacyuser",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    request = _make_request(headers={"authorization": f"Bearer {token}"})
    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=request, session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_ui_user_and_validate_websocket_token_reject_refresh_tokens():
    from app.api.dependencies import get_ui_user, validate_websocket_token

    refresh = create_refresh_token(data={"sub": "testuser"})
    request = _make_request(cookies={"access_token": refresh}, path="/dashboard")

    assert get_ui_user(request) is None
    assert await validate_websocket_token(refresh) is None


@pytest.mark.asyncio
async def test_get_ui_user_and_validate_websocket_token_reject_mfa_pending_tokens():
    from app.api.dependencies import get_ui_user, validate_websocket_token

    pending = create_access_token(
        data={"sub": "testuser", "mfa_pending": True},
        expires_delta=timedelta(minutes=5),
    )
    request = _make_request(cookies={"access_token": pending}, path="/dashboard")

    assert get_ui_user(request) is None
    assert await validate_websocket_token(pending) is None


@pytest.mark.asyncio
async def test_get_ui_user_and_validate_websocket_token_reject_invalidated_tokens():
    from app.api.dependencies import get_ui_user, validate_websocket_token

    access = create_access_token(data={"sub": "revoked-user"})
    request = _make_request(cookies={"access_token": access}, path="/dashboard")

    invalidate_all_user_tokens("revoked-user")

    assert get_ui_user(request) is None
    assert await validate_websocket_token(access) is None


@pytest.mark.asyncio
async def test_validate_websocket_token_rejects_user_invalidated_before():
    from app.api.dependencies import validate_websocket_token

    access = create_access_token(data={"sub": "db-invalidated-user"})
    payload = decode_token(access)

    mock_user = MagicMock()
    mock_user.username = "db-invalidated-user"
    mock_user.is_active = True
    mock_user.invalidated_before = datetime.fromtimestamp(payload["iat"], tz=UTC) + timedelta(seconds=1)

    with patch("app.api.dependencies.async_session_maker", _mock_async_session_maker_with_user(mock_user)):
        assert await validate_websocket_token(access) is None


# ---------------------------------------------------------------------------
# Cookie HttpOnly/Secure flags
# ---------------------------------------------------------------------------


def test_login_response_sets_httponly_secure_cookie():
    """The login endpoint sets cookie with httponly, secure, samesite=strict."""

    # We verify the flags by inspecting the auth router's set_cookie call
    # Rather than spinning up a full app, we verify the code path directly.
    # Extract the login function source to verify set_cookie params are correct
    # This is a structural test — we check the constants used in set_cookie
    import inspect

    from app.api.routers.auth import router

    for _name, _func in inspect.getmembers(router, predicate=inspect.isfunction):
        pass

    # Verify by reading the route definitions for set_cookie calls
    # We look at the actual router endpoints
    routes = [r for r in router.routes if hasattr(r, "path") and r.path == "/token"]
    assert len(routes) == 1, "Expected /token route in auth router"

    # Inspect the endpoint function source
    endpoint = routes[0].endpoint
    source = inspect.getsource(endpoint)
    assert "httponly=True" in source
    assert "secure=True" in source
    assert 'samesite="strict"' in source


def test_logout_deletes_cookie_with_secure_flags():
    """The logout endpoint deletes the cookie with httponly + secure flags."""
    import inspect

    from app.api.routers.auth import router

    routes = [r for r in router.routes if hasattr(r, "path") and r.path == "/logout"]
    assert len(routes) == 1

    endpoint = routes[0].endpoint
    source = inspect.getsource(endpoint)
    assert "delete_cookie" in source
    assert "httponly=True" in source
    assert "secure=True" in source
    assert 'samesite="strict"' in source
