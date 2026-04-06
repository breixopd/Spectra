"""Verify shared package import boundaries."""

import subprocess
import sys


def test_import_boundaries():
    """Shared packages (core, models) must not import service-specific code."""
    result = subprocess.run(
        [sys.executable, "scripts/check_import_boundaries.py"],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent),
    )
    assert result.returncode == 0, f"Import boundary violations:\n{result.stdout}\n{result.stderr}"
