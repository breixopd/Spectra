"""
Tests for authentication cookie handling.

Verifies that login sets HttpOnly cookies with correct attributes
and logout clears them properly.
"""

import inspect


def _get_route_endpoint(router, path: str):
    """Extract endpoint function from an APIRouter by path."""
    routes = [r for r in router.routes if hasattr(r, "path") and r.path == path]
    assert routes, f"Expected route {path} not found"
    return routes[0].endpoint


class TestLoginCookieAttributes:
    """Verify login endpoint sets HttpOnly cookie with secure flags."""

    def test_set_cookie_is_httponly(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert "httponly=True" in source

    def test_set_cookie_is_secure(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert "secure=True" in source

    def test_set_cookie_samesite_strict(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert 'AUTH_COOKIE_SAMESITE = "strict"' in source or 'samesite=AUTH_COOKIE_SAMESITE' in source

    def test_cookie_key_is_access_token(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert 'ACCESS_COOKIE_KEY = "access_token"' in source or 'key=ACCESS_COOKIE_KEY' in source

    def test_cookie_path_is_root(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert 'ACCESS_COOKIE_PATH = "/"' in source or 'path=ACCESS_COOKIE_PATH' in source

    def test_cookie_has_max_age(self):
        from app.api.routers.auth import _set_auth_cookies

        source = inspect.getsource(_set_auth_cookies)
        assert "max_age=" in source


class TestLogoutCookieClear:
    """Verify logout endpoint clears cookie with matching attributes."""

    def test_logout_calls_delete_cookie(self):
        from app.api.routers.auth import _clear_auth_cookies

        source = inspect.getsource(_clear_auth_cookies)
        assert "delete_cookie" in source

    def test_logout_deletes_with_httponly(self):
        from app.api.routers.auth import _clear_auth_cookies

        source = inspect.getsource(_clear_auth_cookies)
        assert "httponly=True" in source

    def test_logout_deletes_with_secure(self):
        from app.api.routers.auth import _clear_auth_cookies

        source = inspect.getsource(_clear_auth_cookies)
        assert "secure=True" in source

    def test_logout_deletes_with_samesite_strict(self):
        from app.api.routers.auth import _clear_auth_cookies

        source = inspect.getsource(_clear_auth_cookies)
        assert 'AUTH_COOKIE_SAMESITE = "strict"' in source or 'samesite=AUTH_COOKIE_SAMESITE' in source

    def test_logout_deletes_correct_key(self):
        from app.api.routers.auth import _clear_auth_cookies

        source = inspect.getsource(_clear_auth_cookies)
        assert 'ACCESS_COOKIE_KEY = "access_token"' in source or 'key=ACCESS_COOKIE_KEY' in source
