"""API route handlers."""

from __future__ import annotations

from importlib import import_module

_ROUTER_MODULES = {
    "health_router": ("spectra_api.api.routers.health", "router"),
    "auth_router": ("spectra_api.api.routers.auth", "router"),
    "tools_router": ("spectra_api.api.routers.tools", "router"),
    "missions_router": ("spectra_api.api.routers.missions", "router"),
    "targets_router": ("spectra_api.api.routers.targets", "router"),
    "findings_router": ("spectra_api.api.routers.findings", "router"),
    "exploits_router": ("spectra_api.api.routers.exploits", "router"),
    "observability_router": ("spectra_api.api.routers.observability", "router"),
    "system_router": ("spectra_api.api.routers.system", "router"),
}

__all__ = list(_ROUTER_MODULES)


def __getattr__(name: str):
    if name not in _ROUTER_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _ROUTER_MODULES[name]
    return getattr(import_module(module_name), attr_name)
