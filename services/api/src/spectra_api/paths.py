"""Filesystem paths for API-owned static assets and templates."""

from pathlib import Path


def api_assets_root() -> Path:
    """Return directory containing sibling ``static/`` and ``templates/``.

    Supports monorepo layout (``services/api/src/spectra_api`` with assets under
    ``services/api``) and API image layout (assets copied into ``/app/spectra_api``).
    """
    pkg = Path(__file__).resolve().parent
    for base in (pkg, *pkg.parents):
        if (base / "static").is_dir() and (base / "templates").is_dir():
            return base
    msg = f"Could not locate API assets root containing static/ and templates/ (started from {pkg})."
    raise RuntimeError(msg)


def static_directory() -> Path:
    return api_assets_root() / "static"


def template_directory() -> Path:
    return api_assets_root() / "templates"
