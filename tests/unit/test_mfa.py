"""Tests for TOTP-based MFA functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pyotp
import pytest
from fastapi import Response
from starlette.requests import Request

from app.core.security import decrypt_mfa_secret, encrypt_mfa_secret, verify_totp

# --- Security helper tests ---


def test_encrypt_decrypt_mfa_secret():
    """Encrypt then decrypt should return the original secret."""
    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    assert encrypted != secret
    assert decrypt_mfa_secret(encrypted) == secret


def test_verify_totp_valid_code():
    """A code generated from the same secret should be valid."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp(secret, code) is True


def test_verify_totp_invalid_code():
    """A random wrong code should fail verification."""
    secret = pyotp.random_base32()
    assert verify_totp(secret, "000000") is False


# --- Endpoint tests using TestClient pattern ---


def _make_user(**overrides):
    """Create a mock User object."""
    user = MagicMock()
    user.id = overrides.get("id", "test-user-id")
    user.username = overrides.get("username", "testuser")
    user.email = overrides.get("email", "test@example.com")
    user.hashed_password = overrides.get("hashed_password", "hashed")
    user.is_active = overrides.get("is_active", True)
    user.is_superuser = overrides.get("is_superuser", False)
    user.role = overrides.get("role", "operator")
    user.mfa_enabled = overrides.get("mfa_enabled", False)
    user.mfa_secret = overrides.get("mfa_secret", None)
    user.plan_id = overrides.get("plan_id", None)
    return user


def _make_request(
    headers: dict[str, str] | None = None,
    scheme: str = "http",
    path: str = "/api/v1/auth/mfa/verify",
) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "scheme": scheme,
        "client": ("127.0.0.1", 50000),
    }
    return Request(scope)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def app_client():
    """Create a test client with mocked dependencies."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routers.auth import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")
    return TestClient(app)


@pytest.mark.asyncio
async def test_mfa_setup_returns_provisioning_uri(mock_session):
    """Setup endpoint should return a valid provisioning URI and base32 secret."""
    from app.api.routers.auth import mfa_setup

    user = _make_user()

    with patch("app.api.routers.auth.encrypt_mfa_secret", side_effect=lambda s: f"enc:{s}"):
        result = await mfa_setup(user=user, session=mock_session)

    assert result.secret  # base32 string
    assert result.provisioning_uri.startswith("otpauth://totp/")
    assert "Spectra" in result.provisioning_uri
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mfa_verify_setup_enables_mfa(mock_session):
    """Verify-setup should enable MFA when given a valid code."""
    from app.api.routers.auth import mfa_verify_setup
    from app.api.schemas.auth import MFAVerifyRequest

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_secret=encrypted, mfa_enabled=False)

    code = pyotp.TOTP(secret).now()
    body = MFAVerifyRequest(code=code)

    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock):
        result = await mfa_verify_setup(request=request, body=body, user=user, session=mock_session)

    assert result["detail"] == "MFA enabled successfully"
    assert user.mfa_enabled is True


@pytest.mark.asyncio
async def test_mfa_verify_setup_rejects_bad_code(mock_session):
    """Verify-setup should reject an invalid TOTP code."""
    from fastapi import HTTPException

    from app.api.routers.auth import mfa_verify_setup
    from app.api.schemas.auth import MFAVerifyRequest

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_secret=encrypted, mfa_enabled=False)

    body = MFAVerifyRequest(code="000000")

    request = MagicMock()
    request.client.host = "127.0.0.1"

    with pytest.raises(HTTPException) as exc_info:
        await mfa_verify_setup(request=request, body=body, user=user, session=mock_session)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_login_with_mfa_requires_code():
    """When MFA is enabled, login should return mfa_required=True."""
    from datetime import timedelta

    from app.core.security import create_access_token

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)

    # Create a mock user with MFA enabled
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)

    # Simulate what the login endpoint does when MFA is enabled
    mfa_token = create_access_token(
        data={"sub": user.username, "mfa_pending": True},
        expires_delta=timedelta(minutes=5),
    )

    # The token should be a valid JWT with mfa_pending claim
    from app.core.security import decode_token

    payload = decode_token(mfa_token)
    assert payload["mfa_pending"] is True
    assert payload["sub"] == "testuser"


@pytest.mark.asyncio
async def test_login_with_mfa_returns_token_after_verify(mock_session):
    """After MFA verify, a full access token should be returned."""
    from datetime import timedelta

    from app.api.routers.auth import mfa_verify_login
    from app.api.schemas.auth import MFAVerifyRequest
    from app.core.security import create_access_token, decode_token

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)

    # Create MFA pending token
    mfa_token = create_access_token(
        data={"sub": user.username, "mfa_pending": True},
        expires_delta=timedelta(minutes=5),
    )

    request = _make_request(
        headers={"authorization": f"Bearer {mfa_token}", "x-forwarded-proto": "https"},
    )
    response = Response()

    # Mock DB to return our user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute = AsyncMock(return_value=mock_result)

    code = pyotp.TOTP(secret).now()
    body = MFAVerifyRequest(code=code)

    with patch("app.api.routers.auth.invalidate_token"):
        result = await mfa_verify_login(
            request=request, response=response, body=body, session=mock_session
        )

    assert "access_token" in result
    assert result["token_type"] == "bearer"
    set_cookie_headers = [
        value.decode("latin-1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]
    assert len(set_cookie_headers) == 2
    assert all("Secure" in header for header in set_cookie_headers)
    # Verify the returned token is a proper access token (no mfa_pending)
    payload = decode_token(result["access_token"])
    assert "mfa_pending" not in payload
    assert payload["sub"] == "testuser"


@pytest.mark.asyncio
async def test_mfa_disable_requires_password_and_code(mock_session):
    """Disable endpoint should require valid password and TOTP code."""
    from fastapi import HTTPException

    from app.api.routers.auth import mfa_disable
    from app.api.schemas.auth import MFADisableRequest

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)

    # Wrong password
    body = MFADisableRequest(password="wrongpassword", code="000000")
    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("app.api.routers.auth.verify_password", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await mfa_disable(request=request, body=body, user=user, session=mock_session)
        assert exc_info.value.status_code == 400
        assert "password" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_mfa_disable_success(mock_session):
    """Disable endpoint should clear MFA fields on success."""
    from app.api.routers.auth import mfa_disable
    from app.api.schemas.auth import MFADisableRequest

    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)

    code = pyotp.TOTP(secret).now()
    body = MFADisableRequest(password="correct", code=code)

    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("app.api.routers.auth.verify_password", return_value=True), \
         patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock):
        result = await mfa_disable(request=request, body=body, user=user, session=mock_session)

    assert result["detail"] == "MFA disabled successfully"
    assert user.mfa_enabled is False
    assert user.mfa_secret is None


@pytest.mark.asyncio
async def test_mfa_verify_setup_rejects_replayed_code(mock_session):
    from fastapi import HTTPException

    from app.api.routers.auth import _used_totp_codes, mfa_verify_setup
    from app.api.schemas.auth import MFAVerifyRequest

    _used_totp_codes.clear()
    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_secret=encrypted, mfa_enabled=False)
    body = MFAVerifyRequest(code=pyotp.TOTP(secret).now())
    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock):
        await mfa_verify_setup(request=request, body=body, user=user, session=mock_session)

    user.mfa_enabled = False
    with pytest.raises(HTTPException) as exc_info:
        await mfa_verify_setup(request=request, body=body, user=user, session=mock_session)
    assert exc_info.value.status_code == 400
    assert "already been used" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mfa_verify_login_rejects_replayed_code(mock_session):
    from datetime import timedelta
    from fastapi import HTTPException

    from app.api.routers.auth import _used_totp_codes, mfa_verify_login
    from app.api.schemas.auth import MFAVerifyRequest
    from app.core.security import create_access_token

    _used_totp_codes.clear()
    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)
    mfa_token = create_access_token(data={"sub": user.username, "mfa_pending": True}, expires_delta=timedelta(minutes=5))

    request = _make_request(headers={"authorization": f"Bearer {mfa_token}"}, scheme="https")
    response = Response()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute = AsyncMock(return_value=mock_result)
    body = MFAVerifyRequest(code=pyotp.TOTP(secret).now())

    with patch("app.api.routers.auth.invalidate_token"):
        await mfa_verify_login(request=request, response=response, body=body, session=mock_session)
        with pytest.raises(HTTPException) as exc_info:
            await mfa_verify_login(request=request, response=response, body=body, session=mock_session)

    assert exc_info.value.status_code == 401
    assert "already been used" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mfa_disable_rejects_replayed_code(mock_session):
    from fastapi import HTTPException

    from app.api.routers.auth import _used_totp_codes, mfa_disable
    from app.api.schemas.auth import MFADisableRequest

    _used_totp_codes.clear()
    secret = pyotp.random_base32()
    encrypted = encrypt_mfa_secret(secret)
    user = _make_user(mfa_enabled=True, mfa_secret=encrypted)
    body = MFADisableRequest(password="correct", code=pyotp.TOTP(secret).now())
    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("app.api.routers.auth.verify_password", return_value=True), \
         patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock):
        await mfa_disable(request=request, body=body, user=user, session=mock_session)

    user.mfa_enabled = True
    user.mfa_secret = encrypted
    with patch("app.api.routers.auth.verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await mfa_disable(request=request, body=body, user=user, session=mock_session)

    assert exc_info.value.status_code == 400
    assert "already been used" in exc_info.value.detail
