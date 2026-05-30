"""Factory surface gated consistently with ``include_routers`` (SERVICE_MODE)."""

from unittest.mock import patch

from starlette.routing import Mount, WebSocketRoute

from spectra_api import factory
from spectra_common.config import settings


def _mount_paths(app) -> set[str]:
    return {m.path for m in app.routes if isinstance(m, Mount)}


def _websocket_paths(app) -> set[str]:
    return {r.path for r in app.routes if isinstance(r, WebSocketRoute)}


def test_create_app_mounts_static_and_ws_when_full_router_mode():
    patched = settings.model_copy(update={"SERVICE_MODE": "api"})
    with patch.object(factory, "settings", patched):
        app = factory.create_app()
    assert "/static" in _mount_paths(app)
    assert "/ws" in _websocket_paths(app)


def test_create_app_omits_static_and_ws_when_core_api_misconfigured():
    """Wrong SERVICE_MODE on the API image: health-only routers, no static/ws."""
    patched = settings.model_copy(update={"SERVICE_MODE": "worker"})
    with patch.object(factory, "settings", patched):
        app = factory.create_app()
    assert "/static" not in _mount_paths(app)
    assert "/ws" not in _websocket_paths(app)
