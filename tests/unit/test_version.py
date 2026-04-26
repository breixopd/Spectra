"""Tests for runtime version resolution."""

from __future__ import annotations

import importlib


def test_version_uses_runtime_env_override(monkeypatch):
    import app._meta.version as version_module

    monkeypatch.setenv("SPECTRA_BUILD_VERSION", "2026.04.13")
    monkeypatch.delenv("SPECTRA_BUILD_VERSION_FILE", raising=False)

    reloaded = importlib.reload(version_module)

    assert reloaded.__version__ == "2026.04.13"


def test_version_uses_runtime_version_file(tmp_path, monkeypatch):
    import app._meta.version as version_module

    version_file = tmp_path / "build-version.txt"
    version_file.write_text("2026.04.13.1\n", encoding="utf-8")

    monkeypatch.delenv("SPECTRA_BUILD_VERSION", raising=False)
    monkeypatch.setenv("SPECTRA_BUILD_VERSION_FILE", str(version_file))

    reloaded = importlib.reload(version_module)

    assert reloaded.__version__ == "2026.04.13.1"
