"""Tests for password reset flow — token creation/verification and API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

# --- Token unit tests ---


class TestCreatePasswordResetToken:
    def test_generates_valid_jwt(self):
        from app.core.security import create_password_reset_token, verify_password_reset_token

        token = create_password_reset_token("user-123")
        assert isinstance(token, str)
        assert len(token) > 20
        # Round-trip: verify should return the user_id
        assert verify_password_reset_token(token) == "user-123"


class TestVerifyPasswordResetToken:
    def test_returns_user_id_for_valid_token(self):
        from app.core.security import create_password_reset_token, verify_password_reset_token

        token = create_password_reset_token("user-456")
        assert verify_password_reset_token(token) == "user-456"

    def test_returns_none_for_expired_token(self):
        from app.core.security import create_password_reset_token, verify_password_reset_token

        token = create_password_reset_token("user-789", expires_minutes=-1)
        assert verify_password_reset_token(token) is None

    def test_returns_none_for_wrong_token_type(self):
        from app.core.security import create_access_token, verify_password_reset_token

        access_token = create_access_token({"sub": "user-000"})
        assert verify_password_reset_token(access_token) is None

    def test_returns_none_for_invalid_token(self):
        from app.core.security import verify_password_reset_token

        assert verify_password_reset_token("not-a-jwt") is None
        assert verify_password_reset_token("") is None


# --- API endpoint tests ---


def _mock_async_session():
    """Build a mock async session context usable by Depends."""
    session = AsyncMock()
    session.add = MagicMock()  # sync method — avoid AsyncMock coroutine warning
    session.commit = AsyncMock()
    return session


def _build_test_client():
    """Return a TestClient with DB dependency overridden."""
    from fastapi.testclient import TestClient

    from app.core.database import get_async_session
    from app.main import app

    mock_session = _mock_async_session()

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = override_session
    client = TestClient(app, raise_server_exceptions=False)
    return client, mock_session


class TestForgotPasswordEndpoint:
    """POST /api/v1/auth/forgot-password always returns 204."""

    def test_returns_204_for_existing_email(self):
        client, mock_session = _build_test_client()
        try:
            fake_user = MagicMock()
            fake_user.id = "user-1"

            with (
                patch("app.api.routers.auth.limiter") as mock_limiter,
                patch(
                    "app.repositories.user.UserRepository.get_by_email", new_callable=AsyncMock, return_value=fake_user
                ),
            ):
                mock_limiter.limit.return_value = lambda f: f
                resp = client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "test@example.com"},
                )
            assert resp.status_code == 204
        finally:
            from app.main import app

            app.dependency_overrides.clear()

    def test_returns_204_for_nonexistent_email(self):
        client, mock_session = _build_test_client()
        try:
            with (
                patch("app.api.routers.auth.limiter") as mock_limiter,
                patch("app.repositories.user.UserRepository.get_by_email", new_callable=AsyncMock, return_value=None),
            ):
                mock_limiter.limit.return_value = lambda f: f
                resp = client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "noone@example.com"},
                )
            assert resp.status_code == 204
        finally:
            from app.main import app

            app.dependency_overrides.clear()


class TestResetPasswordEndpoint:
    """POST /api/auth/reset-password."""

    def test_valid_token_resets_password(self):
        from app.core.security import create_password_reset_token

        token = create_password_reset_token("user-reset")
        client, mock_session = _build_test_client()
        try:
            fake_user = MagicMock()
            fake_user.id = "user-reset"
            fake_user.hashed_password = "old-hash"

            with (
                patch("app.api.routers.auth.limiter") as mock_limiter,
                patch("app.repositories.user.UserRepository.get_by_id", new_callable=AsyncMock, return_value=fake_user),
            ):
                mock_limiter.limit.return_value = lambda f: f
                resp = client.post(
                    "/api/v1/auth/reset-password",
                    json={"token": token, "new_password": "NewPass123"},
                )
            assert resp.status_code == 200
            assert "reset" in resp.json().get("message", "").lower()
        finally:
            from app.main import app

            app.dependency_overrides.clear()

    def test_invalid_token_returns_400(self):
        client, _ = _build_test_client()
        try:
            with patch("app.api.routers.auth.limiter") as mock_limiter:
                mock_limiter.limit.return_value = lambda f: f
                resp = client.post(
                    "/api/v1/auth/reset-password",
                    json={"token": "bogus-token", "new_password": "NewPass123"},
                )
            assert resp.status_code == 400
        finally:
            from app.main import app

            app.dependency_overrides.clear()

    def test_expired_token_returns_400(self):
        from app.core.security import create_password_reset_token

        expired_token = create_password_reset_token("user-exp", expires_minutes=-1)
        client, _ = _build_test_client()
        try:
            with patch("app.api.routers.auth.limiter") as mock_limiter:
                mock_limiter.limit.return_value = lambda f: f
                resp = client.post(
                    "/api/v1/auth/reset-password",
                    json={"token": expired_token, "new_password": "NewPass123"},
                )
            assert resp.status_code == 400
        finally:
            from app.main import app

            app.dependency_overrides.clear()
