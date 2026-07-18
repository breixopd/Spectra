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
    assert f'export SPECTRA_CONTAINER_PREFIX="${{SPECTRA_CONTAINER_PREFIX:-{project_name}-}}"' in script


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


def test_first_run_health_probe_uses_public_host_port_and_configurable_scheme() -> None:
    script = (REPOSITORY_ROOT / "scripts/first_run.sh").read_text()

    assert '"${SPECTRA_PORT:-${APP_PORT:-80}}"' in script
    assert "HEALTH_SCHEME:-http" in script
    assert 'curl "${health_curl_args[@]}" "${health_url}"' in script
    assert "localhost:${APP_PORT:-443}" not in script


def test_maintenance_timers_never_prune_volumes_or_delete_log_files() -> None:
    script = (REPOSITORY_ROOT / "scripts/ops/install-maintenance-timers.sh").read_text()

    assert "docker system prune" not in script
    assert "--volumes" not in script
    assert "/usr/sbin/logrotate /etc/logrotate.conf" in script
    assert "/usr/bin/find /var/log" not in script

    host_maintenance = (REPOSITORY_ROOT / "scripts/ops/host-maintenance.sh").read_text()
    assert "find /var/log" not in host_maintenance
    assert "logrotate /etc/logrotate.conf" in host_maintenance
    assert "label=spectra.managed=true" in host_maintenance
    assert "--volumes" not in host_maintenance


def test_worker_management_retry_job_is_valid_at_top_level_shell_scope() -> None:
    script = (REPOSITORY_ROOT / "scripts/ops/worker_management.sh").read_text()

    assert "local safe_id" not in script
    assert "future release" not in script


@pytest.mark.parametrize(
    "relative_path",
    [
        "deploy/docker/Dockerfile.api",
        "deploy/docker/Dockerfile.ai",
        "deploy/docker/Dockerfile.caddy",
        "deploy/docker/Dockerfile.scheduler",
        "deploy/docker/Dockerfile.worker",
    ],
)
def test_first_party_images_are_marked_for_safe_managed_pruning(relative_path: str) -> None:
    dockerfile = (REPOSITORY_ROOT / relative_path).read_text()

    assert 'spectra.managed="true"' in dockerfile


def test_ui_harness_waits_for_api_liveness_not_full_platform_readiness() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert "/api/healthz" in script
    assert "127.0.0.1:5000/api/health'" not in script


def test_ui_harness_does_not_echo_its_storage_credentials() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert 'export GARAGE_PRINT_CREDENTIALS="${GARAGE_PRINT_CREDENTIALS:-0}"' in script


def test_ui_harness_uses_a_non_hsts_compose_hostname_for_chromium() -> None:
    script = (REPOSITORY_ROOT / "tests/run_ui_tests.sh").read_text()

    assert "APP_BASE_URL=http://${SPECTRA_CONTAINER_PREFIX}app:5000" in script
    assert "APP_BASE_URL=http://app:5000 ui-test-runner" not in script


def test_vulnerable_target_network_is_configurable_for_parallel_worktrees() -> None:
    compose = (REPOSITORY_ROOT / "deploy/docker/compose.yaml").read_text()

    assert "subnet: ${SPECTRA_TARGETS_SUBNET:-10.254.0.0/24}" in compose
    assert "ipv4_address: ${SPECTRA_METASPLOITABLE_IP:-10.254.0.50}" in compose
    assert "ipv4_address: ${SPECTRA_DVWA_IP:-10.254.0.51}" in compose
    assert "TEST_TARGET_IP=${SPECTRA_METASPLOITABLE_IP:-10.254.0.50}" in compose
    assert "PERMISSION_BOUNDARY=${SPECTRA_TARGETS_SUBNET:-10.254.0.0/24}" in compose
    assert "container_name: ${SPECTRA_CONTAINER_PREFIX:-spectra-}app" in compose
    assert "container_name: ${SPECTRA_CONTAINER_PREFIX:-spectra-}db" in compose
    backend_network = compose.split("\n  backend:\n", maxsplit=1)[1].split("\n  sandbox:\n", maxsplit=1)[0]
    assert "subnet:" not in backend_network


def test_live_target_harness_uses_the_configured_container_prefix() -> None:
    script = (REPOSITORY_ROOT / "tests/run_live_tests.sh").read_text()

    assert '"${SPECTRA_CONTAINER_PREFIX}vuln-web"' in script
    assert '"${SPECTRA_CONTAINER_PREFIX}vuln-ssh"' in script
    assert '"${SPECTRA_CONTAINER_PREFIX}vuln-network"' in script
    assert "for target in spectra-vuln-web" not in script


def test_vulnerability_network_target_installs_its_healthcheck_dependency() -> None:
    dockerfile = (REPOSITORY_ROOT / "deploy/docker/targets/Dockerfile.vuln-network").read_text()

    assert "netcat-openbsd" in dockerfile


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


def test_unit_runner_mounts_repository_scripts_for_local_ci_parity() -> None:
    compose = (REPOSITORY_ROOT / "deploy/docker/compose.yaml").read_text()
    unit_runner = compose.split("\n  unit-test-runner:\n", maxsplit=1)[1].split(
        "\n  settings-test-runner:\n", maxsplit=1
    )[0]

    assert "../../scripts:/app/scripts:ro" in unit_runner


def test_caddy_uses_api_liveness_for_proxy_and_container_health() -> None:
    for relative_path in (
        "deploy/docker/Caddyfile.dev",
        "deploy/docker/Caddyfile.test",
        "deploy/docker/Caddyfile.prod",
    ):
        caddyfile = (REPOSITORY_ROOT / relative_path).read_text()
        assert "health_uri /api/healthz" in caddyfile
        assert "health_uri /api/health\n" not in caddyfile
        assert "spectra-app:5000" not in caddyfile

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

    assert "expected_services=(" in workflow
    for service in (
        "db",
        "redis",
        "garage",
        "registry",
        "clickhouse",
        "tensorzero",
        "app",
        "app-replica",
        "ai-svc",
        "scheduler",
        "tools",
        "worker",
        "caddy",
    ):
        assert service in workflow
    assert "Timed out waiting for expected services to start" in workflow
    assert "github.event_name == 'pull_request'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow


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

    assert "--cov-fail-under=65" in ci
    assert "--cov-fail-under=65" in release
    assert "--cov-fail-under=70" not in ci
    assert "--cov-fail-under=70" not in release
    assert "--cov-fail-under=65" in pytest_options["addopts"]
    assert "error::RuntimeWarning" in pytest_options["filterwarnings"]
    assert "error::pytest.PytestUnraisableExceptionWarning" in pytest_options["filterwarnings"]


def test_release_publication_is_gated_by_optional_production_deploy() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release.yml").read_text()
    deploy_block = workflow.split("\n  deploy:\n", maxsplit=1)[1].split("\n  publish:\n", maxsplit=1)[0]
    publish_block = workflow.split("\n  publish:\n", maxsplit=1)[1]

    assert "needs: release" in deploy_block
    assert "needs: [release, deploy]" in publish_block
    assert "needs.deploy.result == 'success'" in publish_block


def test_local_ci_parity_uses_the_same_integration_topology_as_ci() -> None:
    script = (REPOSITORY_ROOT / "scripts/runbooks/ci-parity.sh").read_text()

    assert "ENV_FILE=../../.env.test" in script
    assert "db redis garage tensorzero metasploitable dvwa" in script
    assert "app ai-svc worker tools caddy" in script
    assert "run --rm --no-deps test-runner" in script


def test_landing_hero_uses_a_tracked_product_preview() -> None:
    template = (REPOSITORY_ROOT / "services/api/templates/landing.html").read_text()

    assert "/static/img/product/mission-control.svg" in template
    assert "/static/img/product/mission-control.png" not in template
    assert (REPOSITORY_ROOT / "services/api/static/img/product/mission-control.svg").is_file()
