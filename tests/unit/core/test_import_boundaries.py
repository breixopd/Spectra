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
    from scripts.check_import_boundaries import SERVICE_BOUNDARIES

    assert "app/scheduler_service.py" in SERVICE_BOUNDARIES
    assert "app/worker_service.py" in SERVICE_BOUNDARIES
    assert "app/ai_service.py" in SERVICE_BOUNDARIES
    assert "app/worker" in SERVICE_BOUNDARIES

    # scheduler must not import api or worker
    assert "app.api" in SERVICE_BOUNDARIES["app/scheduler_service.py"]
    assert "app.worker" in SERVICE_BOUNDARIES["app/scheduler_service.py"]

    # worker_service must not import api, scheduler, or ai_service
    assert "app.api" in SERVICE_BOUNDARIES["app/worker_service.py"]
    assert "app.scheduler_service" in SERVICE_BOUNDARIES["app/worker_service.py"]
    assert "app.ai_service" in SERVICE_BOUNDARIES["app/worker_service.py"]

    # ai_service must not import api, worker, or scheduler
    assert "app.api" in SERVICE_BOUNDARIES["app/ai_service.py"]
    assert "app.worker" in SERVICE_BOUNDARIES["app/ai_service.py"]
    assert "app.scheduler_service" in SERVICE_BOUNDARIES["app/ai_service.py"]

    # worker modules must not import api, scheduler, or ai_service
    assert "app.api" in SERVICE_BOUNDARIES["app/worker"]
    assert "app.scheduler_service" in SERVICE_BOUNDARIES["app/worker"]
    assert "app.ai_service" in SERVICE_BOUNDARIES["app/worker"]
