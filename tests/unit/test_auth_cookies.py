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
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert "httponly=True" in source

    def test_set_cookie_is_secure(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert "secure=True" in source

    def test_set_cookie_samesite_strict(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert 'samesite="strict"' in source

    def test_cookie_key_is_access_token(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert 'key="access_token"' in source

    def test_cookie_path_is_root(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert 'path="/"' in source

    def test_cookie_has_max_age(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/token"))
        assert "max_age=" in source


class TestLogoutCookieClear:
    """Verify logout endpoint clears cookie with matching attributes."""

    def test_logout_calls_delete_cookie(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/logout"))
        assert "delete_cookie" in source

    def test_logout_deletes_with_httponly(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/logout"))
        assert "httponly=True" in source

    def test_logout_deletes_with_secure(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/logout"))
        assert "secure=True" in source

    def test_logout_deletes_with_samesite_strict(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/logout"))
        assert 'samesite="strict"' in source

    def test_logout_deletes_correct_key(self):
        from app.api.routers.auth import router

        source = inspect.getsource(_get_route_endpoint(router, "/logout"))
        assert 'key="access_token"' in source
