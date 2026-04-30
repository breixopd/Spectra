"""Spectra API service package."""

from spectra_api.factory import create_app

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name == "app":
        from spectra_api.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
