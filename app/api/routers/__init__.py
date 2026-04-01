"""API route handlers."""

from __future__ import annotations

from importlib import import_module

_ROUTER_MODULES = {
    "health_router": ("app.api.routers.health", "router"),
    "ui_router": ("app.api.routers.ui", "router"),
    "public_router": ("app.api.routers.public", "router"),
    "auth_router": ("app.api.routers.auth", "router"),
    "tools_router": ("app.api.routers.tools", "router"),
    "missions_router": ("app.api.routers.missions", "router"),
    "targets_router": ("app.api.routers.targets", "router"),
    "findings_router": ("app.api.routers.findings", "router"),
    "exploits_router": ("app.api.routers.exploits", "router"),
    "observability_router": ("app.api.routers.observability", "router"),
    "system_router": ("app.api.routers.system", "router"),
}

__all__ = list(_ROUTER_MODULES)


def __getattr__(name: str):
    if name not in _ROUTER_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _ROUTER_MODULES[name]
    return getattr(import_module(module_name), attr_name)
