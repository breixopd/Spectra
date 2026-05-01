"""Tests for authentication cookie handling."""

from fastapi import Request, Response


def _make_request(scheme: str = "https", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "scheme": scheme, "headers": headers or []})


def _set_cookie_headers(response: Response) -> list[str]:
    return [value.decode("latin-1") for key, value in response.raw_headers if key.lower() == b"set-cookie"]


def _cookie_header(response: Response, cookie_key: str) -> str:
    headers = _set_cookie_headers(response)
    for header in headers:
        if header.partition("=")[0] == cookie_key:
            return header
    raise AssertionError(f"Cookie header not found for {cookie_key}: {headers}")


class TestLoginCookieAttributes:
    """Verify auth cookies are written with the expected header attributes."""

    def test_set_access_cookie_header_https(self):
        from spectra_api.api.routers.auth._helpers import (
            ACCESS_COOKIE_KEY,
            ACCESS_COOKIE_PATH,
            _set_auth_cookies,
        )
        from spectra_platform.core.config import settings

        request = _make_request("https")
        response = Response()
        _set_auth_cookies(request, response, "access-token", "refresh-token")

        header = _cookie_header(response, ACCESS_COOKIE_KEY)
        assert header.startswith(f"{ACCESS_COOKIE_KEY}=access-token")
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={ACCESS_COOKIE_PATH}" in header
        assert f"Max-Age={settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}" in header
        assert "samesite=strict" in header.lower()

    def test_set_refresh_cookie_header_http(self):
        from spectra_api.api.routers.auth._helpers import (
            REFRESH_COOKIE_KEY,
            REFRESH_COOKIE_PATH,
            REFRESH_TOKEN_MAX_AGE,
            _set_auth_cookies,
        )

        request = _make_request("http")
        response = Response()
        _set_auth_cookies(request, response, "access-token", "refresh-token")

        header = _cookie_header(response, REFRESH_COOKIE_KEY)
        assert header.startswith(f"{REFRESH_COOKIE_KEY}=refresh-token")
        assert "HttpOnly" in header
        assert "Secure" not in header
        assert f"Path={REFRESH_COOKIE_PATH}" in header
        assert f"Max-Age={REFRESH_TOKEN_MAX_AGE}" in header
        assert "samesite=strict" in header.lower()

    def test_set_cookie_header_prefers_forwarded_proto(self):
        from spectra_api.api.routers.auth._helpers import ACCESS_COOKIE_KEY, _set_auth_cookies

        request = _make_request(
            "http",
            headers=[(b"x-forwarded-proto", b"https")],
        )
        response = Response()
        _set_auth_cookies(request, response, "access-token", "refresh-token")

        header = _cookie_header(response, ACCESS_COOKIE_KEY)
        assert "Secure" in header


class TestLogoutCookieClear:
    """Verify auth cookies are cleared with matching header attributes."""

    def test_clear_access_cookie_header_https(self):
        from spectra_api.api.routers.auth._helpers import (
            ACCESS_COOKIE_KEY,
            ACCESS_COOKIE_PATH,
            _clear_auth_cookies,
        )

        request = _make_request("https")
        response = Response()
        _clear_auth_cookies(request, response)

        header = _cookie_header(response, ACCESS_COOKIE_KEY)
        assert "HttpOnly" in header
        assert "Secure" in header
        assert f"Path={ACCESS_COOKIE_PATH}" in header
        assert "Max-Age=0" in header
        assert "samesite=strict" in header.lower()

    def test_clear_refresh_cookie_header_http(self):
        from spectra_api.api.routers.auth._helpers import (
            REFRESH_COOKIE_KEY,
            REFRESH_COOKIE_PATH,
            _clear_auth_cookies,
        )

        request = _make_request("http")
        response = Response()
        _clear_auth_cookies(request, response)

        header = _cookie_header(response, REFRESH_COOKIE_KEY)
        assert "HttpOnly" in header
        assert "Secure" not in header
        assert f"Path={REFRESH_COOKIE_PATH}" in header
        assert "Max-Age=0" in header
        assert "samesite=strict" in header.lower()
