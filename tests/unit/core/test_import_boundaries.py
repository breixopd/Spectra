"""Verify shared package and cross-service import boundaries."""

import subprocess
import sys


def test_import_boundaries():
    """Shared packages (core, models) must not import service-specific code."""
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
    from scripts.check_import_boundaries import FORBIDDEN_IMPORTS, SERVICE_BOUNDARIES

    assert "services/worker/src/spectra_worker/__main__.py" in SERVICE_BOUNDARIES
    assert "app.services.ai" in FORBIDDEN_IMPORTS
    assert "spectra_ai" in FORBIDDEN_IMPORTS
    assert "spectra_scheduler" in FORBIDDEN_IMPORTS
    assert "services/api/src" in SERVICE_BOUNDARIES
    assert "services/ai/src" in SERVICE_BOUNDARIES
    assert "services/scheduler/src" in SERVICE_BOUNDARIES
    assert "services/worker/src" in SERVICE_BOUNDARIES

    assert "app.api" in SERVICE_BOUNDARIES["services/scheduler/src"]
    assert "spectra_worker" in SERVICE_BOUNDARIES["services/scheduler/src"]

    assert "app.api" in SERVICE_BOUNDARIES["services/worker/src/spectra_worker/__main__.py"]
    assert "spectra_scheduler" in SERVICE_BOUNDARIES["services/worker/src/spectra_worker/__main__.py"]
    assert "spectra_ai" in SERVICE_BOUNDARIES["services/worker/src/spectra_worker/__main__.py"]

    assert "app.api" in SERVICE_BOUNDARIES["services/ai/src"]
    assert "spectra_worker" in SERVICE_BOUNDARIES["services/ai/src"]
    assert "spectra_scheduler" in SERVICE_BOUNDARIES["services/ai/src"]

    assert "spectra_ai" in SERVICE_BOUNDARIES["services/api/src"]
    assert "spectra_worker" in SERVICE_BOUNDARIES["services/api/src"]
    assert "spectra_api" in SERVICE_BOUNDARIES["services/ai/src"]
    assert "spectra_scheduler" in SERVICE_BOUNDARIES["services/worker/src"]
