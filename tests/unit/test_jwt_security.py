"""Tests for JWT security: token type enforcement, refresh token rejection, cookie flags."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    _blacklisted_tokens,
    _blacklist_lock,
)


@pytest.fixture(autouse=True)
def _clear_blacklist():
    with _blacklist_lock:
        _blacklisted_tokens.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()


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

    mock_session = AsyncMock()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=refresh, session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_accepts_access_token():
    """get_current_user accepts a valid access token and fetches the user."""
    from app.api.dependencies import get_current_user

    access = create_access_token(data={"sub": "testuser"})

    mock_user = MagicMock()
    mock_user.username = "testuser"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    user = await get_current_user(token=access, session=mock_session)
    assert user.username == "testuser"


# ---------------------------------------------------------------------------
# Token without type claim
# ---------------------------------------------------------------------------


def test_token_without_type_claim_still_decodes():
    """A legacy token without 'type' can still be decoded by decode_token,
    but get_current_user will reject it since type != 'access'."""
    from jose import jwt
    from app.core.config import settings
    from datetime import datetime, UTC

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
    from app.api.dependencies import get_current_user
    from jose import jwt
    from app.core.config import settings
    from datetime import datetime, UTC
    from fastapi import HTTPException

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
    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, session=mock_session)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Cookie HttpOnly/Secure flags
# ---------------------------------------------------------------------------


def test_login_response_sets_httponly_secure_cookie():
    """The login endpoint sets cookie with httponly, secure, samesite=strict."""
    from starlette.testclient import TestClient
    from unittest.mock import patch as _patch

    # We verify the flags by inspecting the auth router's set_cookie call
    # Rather than spinning up a full app, we verify the code path directly.
    from app.api.routers.auth import router

    # Extract the login function source to verify set_cookie params are correct
    # This is a structural test — we check the constants used in set_cookie
    import inspect

    login_source = None
    for name, func in inspect.getmembers(router, predicate=inspect.isfunction):
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
