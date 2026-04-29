"""Integration test configuration and fixtures.

Provides fixtures specific to integration tests that run without
external services (Redis, PostgreSQL) unless explicitly required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.services.mission.manager import MissionManager


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable slowapi rate limiting for integration tests.

    Without Redis, the SlowAPIMiddleware raises ConnectionError
    which crashes the default handler.
    """
    from app.auth.rate_limit import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def _mock_ws_broadcast():
    """Prevent Mission._broadcast from calling asyncio.create_task outside event loop."""
    with (
        patch("app.services.mission.mission.ws_manager") as mock_ws,
        patch.object(
            __import__("app.services.mission.mission", fromlist=["Mission"]).Mission,
            "_broadcast",
            lambda self, *a, **kw: None,
        ),
    ):
        mock_ws.broadcast_event = AsyncMock()
        mock_ws.broadcast_to_user_event = AsyncMock()
        yield


@pytest_asyncio.fixture(autouse=True)
async def _close_global_async_clients():
    """Close singleton async HTTP clients created by ASGI-style integration tests."""
    yield

    from app.services.gateway.ai_gateway import close_ai_gateway
    from app.services.system.health import close_health_clients
    from app.utils.geoip import close_geoip_session
    from app.core.database import engine

    await close_ai_gateway()
    await close_geoip_session()
    await close_health_clients()
    await engine.dispose()


@pytest.fixture(autouse=True)
def _mock_db_session():
    """Mock database session for ASGI transport tests.

    Routes that depend on ``get_async_session`` get a mock session
    so they don't crash with ConnectionRefusedError when PostgreSQL
    is not running.
    """
    from app.core.database import get_async_session
    from app.main import app

    mock_session = AsyncMock()
    # SELECT 1 for health check
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    async def _mock_get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _mock_get_session
    yield mock_session
    app.dependency_overrides.pop(get_async_session, None)


@pytest_asyncio.fixture
async def mission_manager():
    """MissionManager with background task scheduling disabled.

    Prevents ``asyncio.create_task`` from spawning uncontrolled background
    coroutines that outlive ``with patch(...)`` scopes and crash on DB access.
    """
    from app.services.ai.agents.mission_controller import MissionController
    from app.services.ai.agents.scope import ScopeAgent
    from app.services.ai.consensus import VotingSystem
    from app.services.mission.executor import MissionExecutor
    from tests.mocks.llm import MockLLMClient

    manager = MissionManager()

    # Initialize agents with mock LLM
    mock_llm = MockLLMClient()
    manager.execution.mission_controller = MissionController(mock_llm)
    manager.execution.scope_agent = ScopeAgent(mock_llm)
    manager.execution.executor = MissionExecutor(mock_llm)
    manager.execution.consensus = VotingSystem(mock_llm)
    manager._agents_initialized = True

    # Provide _handle_task_failure on execution manager (refactored to helpers.py)
    from app.services.mission.manager.helpers import handle_task_failure

    async def _handle_task_failure_wrapper(mission, task, error, context):
        await handle_task_failure(
            mission,
            task,
            error,
            context,
            manager.execution.mission_controller,
            manager.execution.consensus,
            manager.steering,
        )

    manager.execution._handle_task_failure = _handle_task_failure_wrapper

    # Replace background task scheduling: run initialize_mission for log
    # generation but skip the full execution loop to prevent uncontrolled
    # coroutines that escape test patch scopes.
    async def _init_only(mission):
        """Run mission init (produces logs) but skip execution loop."""
        try:  # noqa: SIM105
            await manager.lifecycle.initialize_mission(mission)
        except (OSError, RuntimeError, TypeError, AttributeError):
            pass  # Swallow DB/mock errors during init

    def _controlled_schedule(coro):
        coro.close()  # Discard the original coroutine

    _pending_missions: list = []

    original_start = manager.start_mission.__func__  # type: ignore[attr-defined]

    async def _patched_start(*args, **kwargs):
        mid = await original_start(manager, *args, **kwargs)
        # Run initialization inline after start_mission returns
        mission = manager.active_missions.get(mid)
        if mission:
            await _init_only(mission)
        return mid

    manager._schedule_mission_task = _controlled_schedule  # type: ignore[assignment]
    manager.start_mission = _patched_start  # type: ignore[assignment]

    # Mock async_session_maker in modules that tests don't individually patch.
    # Tests already handle lifecycle.async_session_maker and events.emit_sync
    # via inline ``with patch(...)`` blocks, so we only cover state_store
    # and quota_enforcer here.
    #
    # HOWEVER the tests' bare ``patch("...async_session_maker")`` creates a
    # MagicMock that doesn't support ``async with session.begin()``.
    # We also patch lifecycle to provide a proper async-context-manager mock.
    # If a test overlays its own patch, we intercept at the except clause
    # level by widening lifecycle.start_mission's error handling.
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    # Provide a mock begin() that acts as an async context manager
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    class _MockSessionMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    mock_maker = _MockSessionMaker()

    with (
        patch("app.services.mission.manager.lifecycle.async_session_maker", mock_maker),
        patch("app.services.mission.state_store.async_session_maker", mock_maker),
        patch("app.services.billing.quota_enforcer.async_session_maker", mock_maker),
    ):
        yield manager


@pytest.fixture
def test_target_ip():
    """Return a test target IP for integration tests."""
    return "192.168.1.100"
