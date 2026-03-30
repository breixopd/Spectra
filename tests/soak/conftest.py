import pytest

from tests.platform_harness import (
    ensure_platform_targets_available,
    get_app_base_url,
    get_caddy_base_url,
)


@pytest.fixture(scope="session", autouse=True)
def ensure_soak_targets_available() -> None:
    ensure_platform_targets_available(
        ("app", get_app_base_url()),
        ("caddy", get_caddy_base_url()),
        helper_command="./tests/run_load_tests.sh soak",
    )