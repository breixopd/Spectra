"""SERVICE_MODE router mounting behaviour."""

import httpx
import pytest
from fastapi import FastAPI
from starlette.routing import NoMatchFound

from spectra_api.routing import CORE_API_FULL_ROUTER_MODES, include_routers


def _api_paths(app: FastAPI) -> set[str]:
    return set(app.openapi()["paths"])


async def _liveness_status(app: FastAPI) -> int:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://spectra.test",
    ) as client:
        return (await client.get("/api/healthz")).status_code


def test_core_api_full_router_modes_frozen():
    assert frozenset(("", "all", "api")) == CORE_API_FULL_ROUTER_MODES


@pytest.mark.asyncio
async def test_empty_string_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths
    assert await _liveness_status(app) == 200


def test_all_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "all")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths


@pytest.mark.asyncio
async def test_unknown_service_mode_is_fail_closed_health_only():
    app = FastAPI()
    include_routers(app, "definitely_not_a_valid_mode")
    paths = _api_paths(app)
    assert await _liveness_status(app) == 200
    assert "/api/v1/auth/logout" not in paths
    with pytest.raises(NoMatchFound):
        app.url_path_for("logout")


@pytest.mark.asyncio
async def test_api_mode_includes_core_auth_route():
    app = FastAPI()
    include_routers(app, "api")
    paths = _api_paths(app)
    assert "/api/v1/auth/logout" in paths
    assert await _liveness_status(app) == 200
