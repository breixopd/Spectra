"""Filesystem paths for static assets relative to Spectra workspace or /app."""

from pathlib import Path


def repo_root_with_assets() -> Path:
    """Return directory containing sibling ``static/`` and ``templates/``.

    Supports monorepo layout (``services/api/src/spectra_api``) and API image layout
    (``/app/spectra_api`` with assets under ``/app``).
    """
    pkg = Path(__file__).resolve().parent
    for base in (pkg.parent, *pkg.parents):
        if (base / "static").is_dir() and (base / "templates").is_dir():
            return base
    msg = (
        "Could not locate project root containing static/ and templates/ "
        f"(started from {pkg})."
    )
    raise RuntimeError(msg)


def static_directory() -> Path:
    return repo_root_with_assets() / "static"
