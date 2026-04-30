"""Spectra API service package."""

from spectra_api.factory import create_app
from spectra_api.main import app

__all__ = ["app", "create_app"]
