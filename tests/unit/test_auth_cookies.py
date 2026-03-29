"""Tests for authentication cookie handling."""

from fastapi import Response


def _set_cookie_headers(response: Response) -> list[str]:
    return [
        value.decode("latin-1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]


def _cookie_header(response: Response, cookie_key: str) -> str:
    headers = _set_cookie_headers(response)
    for header in headers:
        if header.partition("=")[0] == cookie_key:
            return header
    raise AssertionError(f"Cookie header not found for {cookie_key}: {headers}")


class TestLoginCookieAttributes:
    """Verify auth cookies are written with the expected header attributes."""

    def test_set_access_cookie_header(self):
        from app.api.routers.auth import (
            ACCESS_COOKIE_KEY,
            ACCESS_COOKIE_PATH,
            _set_auth_cookies,
        )
        from app.core.config import settings

        response = Response()
        _set_auth_cookies(response, "access-token", "refresh-token")

        header = _cookie_header(response, ACCESS_COOKIE_KEY)
        assert header.startswith(f"{ACCESS_COOKIE_KEY}=access-token")
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={ACCESS_COOKIE_PATH}" in header
        assert f"Max-Age={settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}" in header
        assert "samesite=strict" in header.lower()

    def test_set_refresh_cookie_header(self):
        from app.api.routers.auth import (
            REFRESH_COOKIE_KEY,
            REFRESH_COOKIE_PATH,
            REFRESH_TOKEN_MAX_AGE,
            _set_auth_cookies,
        )

        response = Response()
        _set_auth_cookies(response, "access-token", "refresh-token")

        header = _cookie_header(response, REFRESH_COOKIE_KEY)
        assert header.startswith(f"{REFRESH_COOKIE_KEY}=refresh-token")
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={REFRESH_COOKIE_PATH}" in header
        assert f"Max-Age={REFRESH_TOKEN_MAX_AGE}" in header
        assert "samesite=strict" in header.lower()


class TestLogoutCookieClear:
    """Verify auth cookies are cleared with matching header attributes."""

    def test_clear_access_cookie_header(self):
        from app.api.routers.auth import (
            ACCESS_COOKIE_KEY,
            ACCESS_COOKIE_PATH,
            _clear_auth_cookies,
        )

        response = Response()
        _clear_auth_cookies(response)

        header = _cookie_header(response, ACCESS_COOKIE_KEY)
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={ACCESS_COOKIE_PATH}" in header
        assert "Max-Age=0" in header
        assert "samesite=strict" in header.lower()

    def test_clear_refresh_cookie_header(self):
        from app.api.routers.auth import (
            REFRESH_COOKIE_KEY,
            REFRESH_COOKIE_PATH,
            _clear_auth_cookies,
        )

        response = Response()
        _clear_auth_cookies(response)

        header = _cookie_header(response, REFRESH_COOKIE_KEY)
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={REFRESH_COOKIE_PATH}" in header
        assert "Max-Age=0" in header
        assert "samesite=strict" in header.lower()
