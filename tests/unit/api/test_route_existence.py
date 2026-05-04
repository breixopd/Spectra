"""
Route existence matrix — verifies that critical API endpoints are registered.

Each test asserts that a specific path pattern is present in app.routes so that
gaps introduced by router registration errors are caught before they reach
production.
"""

import pytest
from fastapi.routing import APIRoute


def _registered_paths() -> set[str]:
    """Collect all APIRoute paths from the main FastAPI application."""
    from spectra_api.main import app

    return {route.path for route in app.routes if isinstance(route, APIRoute)}


# Paths that must be present.  Uses FastAPI's {param} syntax for parametrised
# segments, which is the format stored in route.path after include_router.
_REQUIRED_ROUTES = [
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
    "/api/v1/auth/mfa/cancel",
    "/api/v1/system/public-status",
    "/api/v1/system/status",
    "/api/v1/system/audit-log",
    "/api/v1/auth/api-keys",
    "/api/v1/auth/activity",
    "/api/v1/pentest-sessions/{session_id}/manual-state",
]


class TestRouteExistence:
    """Core API routes are registered in the FastAPI application."""

    @pytest.mark.parametrize("path", _REQUIRED_ROUTES)
    def test_route_exists(self, path):
        all_paths = _registered_paths()
        assert path in all_paths, (
            f"Route {path!r} is not registered. "
            f"Check include_router() calls in spectra_api/routing.py. "
            f"Registered paths matching 'auth': "
            f"{sorted(p for p in all_paths if '/auth/' in p)}"
        )

    def test_auth_logout_has_post_method(self):
        from spectra_api.main import app

        routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/auth/logout"]
        assert routes, "Route /api/v1/auth/logout not found"
        assert "POST" in routes[0].methods

    def test_auth_refresh_has_post_method(self):
        from spectra_api.main import app

        routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/auth/refresh"]
        assert routes, "Route /api/v1/auth/refresh not found"
        assert "POST" in routes[0].methods

    def test_mfa_cancel_has_post_method(self):
        from spectra_api.main import app

        routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/auth/mfa/cancel"]
        assert routes, "Route /api/v1/auth/mfa/cancel not found"
        assert "POST" in routes[0].methods

    def test_public_status_has_get_method(self):
        from spectra_api.main import app

        routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/system/public-status"]
        assert routes, "Route /api/v1/system/public-status not found"
        assert "GET" in routes[0].methods

    def test_manual_state_has_both_put_and_get(self):
        from spectra_api.main import app

        path = "/api/v1/pentest-sessions/{session_id}/manual-state"
        routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == path]
        assert len(routes) >= 2, f"Expected PUT and GET for {path}, found {len(routes)}"
        methods = set()
        for r in routes:
            methods.update(r.methods or set())
        assert "PUT" in methods
        assert "GET" in methods
