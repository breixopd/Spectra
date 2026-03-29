"""Live smoke tests for safe ops scripts against running test containers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_inspect_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


@pytest.fixture(scope="module")
def ops_env() -> dict[str, str]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required for live ops smoke tests")

    required_env = {
        "OPS_DB_CONTAINER": os.getenv("OPS_DB_CONTAINER", ""),
        "OPS_APP_CONTAINER": os.getenv("OPS_APP_CONTAINER", ""),
        "OPS_MINIO_CONTAINER": os.getenv("OPS_MINIO_CONTAINER", ""),
        "OPS_MINIO_ROOT_USER": os.getenv("OPS_MINIO_ROOT_USER", ""),
        "OPS_MINIO_ROOT_PASSWORD": os.getenv("OPS_MINIO_ROOT_PASSWORD", ""),
    }

    missing = [name for name, value in required_env.items() if not value]
    if missing:
        pytest.skip(f"live ops smoke tests require env vars: {', '.join(missing)}")

    unavailable = [
        name for name in ("OPS_DB_CONTAINER", "OPS_APP_CONTAINER", "OPS_MINIO_CONTAINER")
        if not _docker_inspect_running(required_env[name])
    ]
    if unavailable:
        pytest.skip(f"required live containers are unavailable: {', '.join(unavailable)}")

    env = os.environ.copy()
    env.update(
        {
            "DB_CONTAINER": required_env["OPS_DB_CONTAINER"],
            "DB_USER": os.getenv("OPS_DB_USER", "spectra"),
            "DB_NAME": os.getenv("OPS_DB_NAME", "spectra_test"),
            "APP_CONTAINER": required_env["OPS_APP_CONTAINER"],
            "MINIO_CONTAINER": required_env["OPS_MINIO_CONTAINER"],
            "MINIO_ROOT_USER": required_env["OPS_MINIO_ROOT_USER"],
            "MINIO_ROOT_PASSWORD": required_env["OPS_MINIO_ROOT_PASSWORD"],
            "MINIO_URL": os.getenv("OPS_MINIO_URL", "http://127.0.0.1:19000"),
            "WORKER_CONTAINER": os.getenv("OPS_WORKER_CONTAINER", "spectra-test-worker-missing"),
            "SCHEDULER_CONTAINER": os.getenv("OPS_SCHEDULER_CONTAINER", "spectra-test-scheduler-missing"),
            "AI_CONTAINER": os.getenv("OPS_AI_CONTAINER", "spectra-test-ai-missing"),
            "CADDY_CONTAINER": os.getenv("OPS_CADDY_CONTAINER", "spectra-test-caddy-missing"),
        }
    )
    return env


def _run_script(ops_env: dict[str, str], script_path: str, *args: str) -> str:
    result = subprocess.run(
        [script_path, *args],
        cwd=REPO_ROOT,
        env=ops_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    output = f"{result.stdout}{result.stderr}"
    assert result.returncode == 0, output
    return output


@pytest.mark.parametrize(
    ("script_path", "args", "label"),
    [
        ("./scripts/ops/db_maintenance.sh", ("stats",), "db-stats"),
        ("./scripts/ops/user_management.sh", ("list",), "user-list"),
        ("./scripts/ops/incident_response.sh", ("active-sessions",), "active-sessions"),
        ("./scripts/ops/worker_management.sh", ("status",), "worker-status"),
        ("./scripts/ops/backup_restore.sh", ("list",), "backup-list"),
        ("./scripts/ops/s3_management.sh", ("health",), "s3-health"),
        ("./scripts/ops/log_management.sh", ("sizes",), "log-sizes"),
    ],
    ids=lambda value: value,
)
def test_safe_ops_scripts_smoke(ops_env: dict[str, str], script_path: str, args: tuple[str, ...], label: str) -> None:
    output = _run_script(ops_env, script_path, *args)

    if label == "db-stats":
        assert "Active connections:" in output
        assert "Connection counts by state:" in output
        assert "Table statistics:" in output
    elif label == "user-list":
        assert "username" in output
        assert "email" in output
        assert "role" in output
    elif label == "active-sessions":
        assert "Users with valid sessions" in output
        assert "username" in output
    elif label == "worker-status":
        assert "=== Job Queue Statistics ===" in output
        assert "Jobs by type:" in output
    elif label == "backup-list":
        assert "Backups in S3:" in output
        assert "No backups found." in output or "s3://" in output
    elif label == "s3-health":
        assert "MinIO health:" in output
        assert "OK" in output
    elif label == "log-sizes":
        assert "Container log sizes:" in output
        assert ops_env["APP_CONTAINER"] in output
        assert ops_env["DB_CONTAINER"] in output
        assert ops_env["MINIO_CONTAINER"] in output
    else:
        raise AssertionError(f"Unhandled smoke test label: {label}")