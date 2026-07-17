"""
Route existence matrix — verifies that critical API endpoints are registered.

Each test asserts against FastAPI's generated OpenAPI contract. FastAPI 0.137+
preserves the nested router tree, so ``app.routes`` is no longer a flat list of
``APIRoute`` instances.
"""

import pytest


def _registered_paths() -> set[str]:
    """Collect public API paths from FastAPI's supported contract surface."""
    from spectra_api.main import app

    return set(app.openapi()["paths"])


def _registered_methods(path: str) -> set[str]:
    from spectra_api.main import app

    return set(app.openapi()["paths"].get(path, {}))


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
        assert "post" in _registered_methods("/api/v1/auth/logout")

    def test_auth_refresh_has_post_method(self):
        assert "post" in _registered_methods("/api/v1/auth/refresh")

    def test_mfa_cancel_has_post_method(self):
        assert "post" in _registered_methods("/api/v1/auth/mfa/cancel")

    def test_public_status_has_get_method(self):
        assert "get" in _registered_methods("/api/v1/system/public-status")

    def test_manual_state_has_both_put_and_get(self):
        path = "/api/v1/pentest-sessions/{session_id}/manual-state"
        assert {"get", "put"} <= _registered_methods(path)
