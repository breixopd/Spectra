"""Admin panel API router."""

from __future__ import annotations

from importlib import import_module

from fastapi import APIRouter

_ADMIN_ROUTER_MODULES = {
    "users_router": "spectra_api.api.routers.admin.users",
    "plans_router": "spectra_api.api.routers.admin.plans",
    "servers_router": "spectra_api.api.routers.admin.servers",
    "audit_router": "spectra_api.api.routers.admin.audit",
    "content_router": "spectra_api.api.routers.admin.content",
    "email_router": "spectra_api.api.routers.admin.email",
    "settings_router": "spectra_api.api.routers.admin.settings",
    "tensorzero_router": "spectra_api.api.routers.admin.tensorzero",
    "monitoring_router": "spectra_api.api.routers.admin.monitoring",
    "rollback_router": "spectra_api.api.routers.admin.rollback",
    "training_router": "spectra_api.api.routers.admin.training",
}

__all__ = ["router", *list(_ADMIN_ROUTER_MODULES)]  # noqa: PLE0604


def _load_router(name: str):
    module = import_module(_ADMIN_ROUTER_MODULES[name])
    value = module.router
    globals()[name] = value
    return value


def __getattr__(name: str):
    if name == "router":
        root = APIRouter()
        for child_name in _ADMIN_ROUTER_MODULES:
            root.include_router(_load_router(child_name))
        globals()[name] = root
        return root
    if name in _ADMIN_ROUTER_MODULES:
        return _load_router(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
