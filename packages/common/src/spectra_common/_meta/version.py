"""Spectra version resolution.

Release images inject the authoritative build version at runtime so the release
workflow can tag the exact source commit that produced the artifacts without
rewriting tracked source files.
"""

from __future__ import annotations

import os
from pathlib import Path

# Source checkouts and local host runs are development builds.  Release images
# always inject the immutable CalVer through ``SPECTRA_BUILD_VERSION`` or the
# build-version file, so this fallback must never masquerade as an old release.
DEFAULT_VERSION = "dev"
_VERSION_ENV_VAR = "SPECTRA_BUILD_VERSION"
_VERSION_FILE_ENV_VAR = "SPECTRA_BUILD_VERSION_FILE"
_DEFAULT_VERSION_FILE = Path("/app/.build-version")


def _read_version_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _resolve_version() -> str:
    env_version = os.getenv(_VERSION_ENV_VAR, "").strip()
    if env_version:
        return env_version

    version_file = Path(os.getenv(_VERSION_FILE_ENV_VAR, str(_DEFAULT_VERSION_FILE)))
    file_version = _read_version_file(version_file)
    if file_version:
        return file_version

    return DEFAULT_VERSION


__version__ = _resolve_version()
