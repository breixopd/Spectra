import pytest
import pytest_asyncio

from tests.platform_harness import (
    ensure_platform_targets_available,
    get_app_base_url,
    get_caddy_base_url,
    reset_rate_limit_state_if_requested,
)


@pytest.fixture(scope="session", autouse=True)
def ensure_load_targets_available() -> None:
    ensure_platform_targets_available(
        ("app", get_app_base_url()),
        ("caddy", get_caddy_base_url()),
        helper_command="./tests/run_load_tests.sh load",
    )


@pytest_asyncio.fixture(autouse=True)
async def reset_rate_limit_state_between_load_tests() -> None:
    await reset_rate_limit_state_if_requested()