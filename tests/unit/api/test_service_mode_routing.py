"""SERVICE_MODE router mounting behaviour."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from spectra_api.routing import CORE_API_FULL_ROUTER_MODES, include_routers


def _api_paths(app: FastAPI) -> set[str]:
    return {r.path for r in app.routes if isinstance(r, APIRoute)}


def test_core_api_full_router_modes_frozen():
    assert CORE_API_FULL_ROUTER_MODES == frozenset(("", "all", "api"))


def test_empty_string_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths
    assert "/api/healthz" in paths


def test_all_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "all")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths


def test_unknown_service_mode_is_fail_closed_health_only():
    app = FastAPI()
    include_routers(app, "definitely_not_a_valid_mode")
    paths = _api_paths(app)
    assert "/api/healthz" in paths
    assert "/api/v1/auth/logout" not in paths


def test_api_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "api")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths
    assert "/api/healthz" in paths
