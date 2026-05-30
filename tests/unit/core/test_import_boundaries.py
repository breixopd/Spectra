"""Verify shared package and cross-service import boundaries."""

import subprocess
import sys


def test_import_boundaries():
    """Bounded packages must not import service packages."""
    result = subprocess.run(
        [sys.executable, "scripts/check_import_boundaries.py"],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent),
        check=False,
    )
    assert result.returncode == 0, f"Import boundary violations:\n{result.stdout}\n{result.stderr}"


def test_service_boundary_rules_exist():
    """Verify the boundary checker defines cross-service rules."""
    from scripts.check_import_boundaries import SERVICE_FORBIDDEN, SERVICE_PACKAGES

    assert "spectra_ai" in SERVICE_PACKAGES
    assert "spectra_api" in SERVICE_PACKAGES
    assert "spectra_scheduler" in SERVICE_PACKAGES
    assert "spectra_worker" in SERVICE_PACKAGES

    assert "services/api/src" in SERVICE_FORBIDDEN
    assert "services/ai/src" in SERVICE_FORBIDDEN
    assert "services/scheduler/src" in SERVICE_FORBIDDEN
    assert "services/worker/src" in SERVICE_FORBIDDEN

    assert "spectra_ai" in SERVICE_FORBIDDEN["services/api/src"]
    assert "spectra_worker" in SERVICE_FORBIDDEN["services/api/src"]
    assert "spectra_api" in SERVICE_FORBIDDEN["services/ai/src"]
    assert "spectra_worker" in SERVICE_FORBIDDEN["services/ai/src"]
    assert "spectra_api" in SERVICE_FORBIDDEN["services/scheduler/src"]
    assert "spectra_ai" in SERVICE_FORBIDDEN["services/scheduler/src"]
    assert "spectra_api" in SERVICE_FORBIDDEN["services/worker/src"]
    assert "spectra_ai" in SERVICE_FORBIDDEN["services/worker/src"]
    assert "spectra_scheduler" in SERVICE_FORBIDDEN["services/worker/src"]
