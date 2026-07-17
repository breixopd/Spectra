"""Regression tests for repository-owned operational entry points."""

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

    assert (
        f'export COMPOSE_PROJECT_NAME="${{COMPOSE_PROJECT_NAME:-{project_name}}}"'
        in script
    )


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
