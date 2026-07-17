"""Regression tests for repository-owned operational entry points."""

import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative_path",
    [
        "tests/run_ui_tests.sh",
        "tests/run_load_tests.sh",
        "tests/run_live_tests.sh",
        "scripts/runbooks/full-test-matrix.sh",
    ],
)
def test_test_harnesses_use_the_deployed_garage_bootstrap(relative_path: str) -> None:
    script = (REPOSITORY_ROOT / relative_path).read_text()

    assert "deploy/docker/garage-init.sh" in script
    assert '"${PROJECT_ROOT}/docker/garage-init.sh"' not in script
    assert '"${PROJECT_DIR}/docker/garage-init.sh"' not in script
    assert "bash ./docker/garage-init.sh" not in script
    assert '"${ROOT}/docker/garage-init.sh"' not in script


@pytest.mark.parametrize(
    ("relative_path", "project_name"),
    [
        ("tests/run_ui_tests.sh", "spectra-ui-tests"),
        ("tests/run_load_tests.sh", "spectra-load-tests"),
        ("tests/run_live_tests.sh", "spectra-live-tests"),
        ("scripts/runbooks/full-test-matrix.sh", "spectra-full-matrix"),
    ],
)
def test_docker_harnesses_default_to_an_isolated_compose_project(
    relative_path: str,
    project_name: str,
) -> None:
    script = (REPOSITORY_ROOT / relative_path).read_text()

    assert f'export COMPOSE_PROJECT_NAME="${{COMPOSE_PROJECT_NAME:-{project_name}}}"' in script


@pytest.mark.parametrize("relative_path", ["scripts/first_run.sh", "scripts/deploy.sh"])
def test_operator_startup_scripts_explicitly_enable_the_app_profile(
    relative_path: str,
) -> None:
    script = (REPOSITORY_ROOT / relative_path).read_text()

    assert 'COMPOSE_PROFILES="${COMPOSE_PROFILES:-app}"' in script


def test_first_run_fails_when_application_readiness_times_out() -> None:
    script = (REPOSITORY_ROOT / "scripts/first_run.sh").read_text()
    timeout_block = script.split("Application health check timed out", maxsplit=1)[1]

    assert "exit 1" in timeout_block.split("# ── Summary", maxsplit=1)[0]


def test_ui_harness_waits_for_api_liveness_not_full_platform_readiness() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert "/api/healthz" in script
    assert "127.0.0.1:5000/api/health'" not in script


def test_ui_harness_does_not_echo_its_storage_credentials() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert 'export GARAGE_PRINT_CREDENTIALS="${GARAGE_PRINT_CREDENTIALS:-0}"' in script


def test_ui_harness_uses_a_non_hsts_compose_hostname_for_chromium() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert "APP_BASE_URL=http://spectra-app:5000" in script
    assert "APP_BASE_URL=http://app:5000 ui-test-runner" not in script


def test_vulnerable_target_network_is_configurable_for_parallel_worktrees() -> None:
    compose = (REPOSITORY_ROOT / "deploy/docker/compose.yaml").read_text()

    assert "subnet: ${SPECTRA_TARGETS_SUBNET:-10.254.0.0/24}" in compose
    assert "ipv4_address: ${SPECTRA_METASPLOITABLE_IP:-10.254.0.50}" in compose
    assert "ipv4_address: ${SPECTRA_DVWA_IP:-10.254.0.51}" in compose
    assert "TEST_TARGET_IP=${SPECTRA_METASPLOITABLE_IP:-10.254.0.50}" in compose
    assert "PERMISSION_BOUNDARY=${SPECTRA_TARGETS_SUBNET:-10.254.0.0/24}" in compose


def test_test_environment_boots_tensorzero_without_a_live_provider_secret() -> None:
    test_env = (REPOSITORY_ROOT / ".env.test.example").read_text()

    assert "DEEPSEEK_API_KEY=test-deepseek-api-key" in test_env
    assert "LOG_LEVEL=INFO" in test_env


def test_compose_api_healthcheck_is_liveness_and_does_not_pull_compute_plane() -> None:
    compose = (REPOSITORY_ROOT / "deploy/docker/compose.yaml").read_text()
    app_service = compose.split("\n  app:\n", maxsplit=1)[1].split("\n  ai-svc:\n", maxsplit=1)[0]

    assert "http://localhost:5000/api/healthz" in app_service
    dependency_block = app_service.split("    depends_on:\n", maxsplit=1)[1].split("    environment:\n", maxsplit=1)[0]
    for service in ("ai-svc", "tensorzero", "scheduler", "worker"):
        assert f"      {service}:" not in dependency_block


def test_caddy_uses_api_liveness_for_proxy_and_container_health() -> None:
    for relative_path in (
        "deploy/docker/Caddyfile.dev",
        "deploy/docker/Caddyfile.test",
        "deploy/docker/Caddyfile.prod",
    ):
        caddyfile = (REPOSITORY_ROOT / relative_path).read_text()
        assert "health_uri /api/healthz" in caddyfile
        assert "health_uri /api/health\n" not in caddyfile

    compose = (REPOSITORY_ROOT / "deploy/docker/compose.yaml").read_text()
    caddy_service = compose.split("\n  caddy:\n", maxsplit=1)[1].split("\n  app:\n", maxsplit=1)[0]
    assert "http://localhost:80/api/healthz" in caddy_service


def test_api_image_healthcheck_is_liveness() -> None:
    dockerfile = (REPOSITORY_ROOT / "deploy/docker/Dockerfile.api").read_text()

    assert "http://localhost:5000/api/healthz" in dockerfile
    assert "http://localhost:5000/api/health || exit 1" not in dockerfile


def test_playwright_image_matches_the_locked_browser_driver() -> None:
    lock = tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text())
    playwright = next(package for package in lock["package"] if package["name"] == "playwright")
    dockerfile = (REPOSITORY_ROOT / "deploy/docker/Dockerfile.playwright").read_text()

    assert f"playwright/python:v{playwright['version']}-noble" in dockerfile


def test_compose_smoke_fails_if_the_full_stack_never_starts() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()

    assert 'if [ "${all_running:-0}" -lt 10 ]; then' in workflow
    assert "Timed out waiting for all managed services to start" in workflow


def test_ci_verifies_first_party_worker_tool_entry_points() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()

    assert "Verify first-party worker tool entry points" in workflow
    assert "imds-fetcher --version && graphql-fuzzer --version" in workflow


def test_ci_enforces_python_formatting() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()

    assert "python -m ruff format --check tests/ services/ packages/ scripts/ db/" in workflow


def test_ci_and_release_share_the_measured_coverage_floor() -> None:
    ci = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()
    release = (REPOSITORY_ROOT / ".github/workflows/release.yml").read_text()
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    assert "--cov-fail-under=67" in ci
    assert "--cov-fail-under=67" in release
    assert "--cov-fail-under=70" not in ci
    assert "--cov-fail-under=70" not in release
    assert "--cov-fail-under=67" in pytest_options["addopts"]
    assert "error::RuntimeWarning" in pytest_options["filterwarnings"]
    assert "error::pytest.PytestUnraisableExceptionWarning" in pytest_options["filterwarnings"]


def test_local_ci_parity_uses_the_same_integration_topology_as_ci() -> None:
    script = (REPOSITORY_ROOT / "scripts/runbooks/ci-parity.sh").read_text()

    assert "ENV_FILE=../../.env.test" in script
    assert "db redis garage tensorzero metasploitable dvwa" in script
    assert "app ai-svc worker tools caddy" in script
    assert "run --rm --no-deps test-runner" in script
