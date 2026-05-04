"""Focused tests for Swarm deploy image version extraction."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts/ops/swarm_deploy.sh"


def _run_extract_version(image_ref: str) -> subprocess.CompletedProcess[str]:
    command = f"source {shlex.quote(str(SCRIPT_PATH))} && extract_version_from_image {shlex.quote(image_ref)}"
    return subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def test_extract_version_from_digest_qualified_image_ref() -> None:
    result = _run_extract_version("ghcr.io/breixopd14/spectra-app:2026.04.13@sha256:deadbeef")

    assert result.returncode == 0
    assert result.stdout.strip() == "2026.04.13"


def test_extract_version_from_digest_qualified_image_ref_with_registry_port() -> None:
    result = _run_extract_version("registry.example.com:5443/team/spectra-app:2026.04.13.1@sha256:deadbeef")

    assert result.returncode == 0
    assert result.stdout.strip() == "2026.04.13.1"


def test_extract_version_fails_closed_without_authoritative_tag() -> None:
    result = _run_extract_version("registry.example.com:5443/team/spectra-app@sha256:deadbeef")

    assert result.returncode != 0
    assert result.stdout.strip() == ""
