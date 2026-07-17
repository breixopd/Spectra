"""
Root test configuration and fixtures.

Provides common fixtures used across all test modules.

NOTE: Live tests (marked with @pytest.mark.live) should NOT use mocks.
The mocking fixtures here only apply to unit tests.
"""

import asyncio
import contextlib
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Pin runtime-writable paths to an ephemeral temp dir BEFORE any app module (and its
# settings singleton) is imported, so a bind-mounted source tree never accumulates
# test/dev artifacts like data/.encryption_key. setdefault respects explicit overrides
# from CI or .env.test.
_TEST_DATA_DIR = os.path.join(tempfile.gettempdir(), "spectra-test-data")
os.makedirs(_TEST_DATA_DIR, exist_ok=True)
os.environ.setdefault("DATA_DIR", _TEST_DATA_DIR)


@pytest.fixture(autouse=True, scope="session")
def cleanup_test_logs():
    """Clean up test log files before and after the test session."""
    log_path = "logs/spectra_testing.log"
    yield
    if os.path.exists(log_path):
        os.remove(log_path)


def _is_live_test(item: pytest.Item) -> bool:
    """Check if a test should bypass unit-test mocking.

    Returns True for tests marked @pytest.mark.live, files named
    ``test_live*``, and anything under the ``tests/integration/``
    directory (integration tests manage their own fixtures).
    """
    if item.get_closest_marker("live"):
        return True
    fspath = str(item.fspath)
    if "test_live" in fspath:
        return True
    if "/integration/" in fspath or "\\integration\\" in fspath:
        return True
    return bool("/e2e/" in fspath or "\\e2e\\" in fspath)


@pytest_asyncio.fixture
async def real_mission_manager():
    """Provide a real MissionManager instance for live tests."""
    import spectra_ai_core.llm as llm_module
    from spectra_ai_core.llm import get_default_llm_client
    from spectra_mission.manager import MissionManager

    # Use real LLM client (configured via env vars/settings)
    real_llm = get_default_llm_client()

    # Patch the global client
    original_client = llm_module._global_llm_client
    llm_module._global_llm_client = real_llm

    # Patch VotingSystem to be more lenient for tests
    from spectra_ai_core import consensus

    original_init = consensus.VotingSystem.__init__

    def new_init(self, llm, config=None):
        if config is None:
            # Use single voter for tests to avoid timeouts and consensus issues with small models
            config = consensus.VotingConfig(num_voters=1, k_threshold=1, min_confidence=0.5)
        original_init(self, llm, config)

    # Apply patch
    import pytest

    with pytest.MonkeyPatch.context() as m:
        m.setattr(consensus.VotingSystem, "__init__", new_init)

        manager = MissionManager()
        yield manager

    # Cleanup
    if hasattr(real_llm, "close"):
        await real_llm.close()

    # Restore
    llm_module._global_llm_client = original_client


@pytest.fixture(autouse=True)
def mock_websocket_for_unit_tests(request):
    """
    Mock WebSocket broadcast for unit tests only.

    Live tests (marked with @pytest.mark.live) bypass this mock
    to test real WebSocket functionality.
    """
    # Skip mocking for live tests
    if _is_live_test(request.node):
        yield
        return

    # Create a mock that returns a completed coroutine
    mock_broadcast = AsyncMock(return_value=None)

    # Also mock create_task to handle cases in sync tests
    original_create_task = asyncio.create_task

    # Background function names that must never run as real tasks in unit tests.
    _BACKGROUND_CORO_NAMES = frozenset(
        {
            "cache_cleanup_loop",
            "periodic_cleanup_loop",
            "load_embeddings_with_status",
            "_initialize_services.<locals>.load_embeddings_with_status",
            "_initialize_services.<locals>._init_exploit_db",
            "_init_exploit_db",
            "_config_change_listener",
            "_blacklist_change_listener",
            "_keepalive",
            "AsyncMockMixin._execute_mock_call",
            "embedded_ops_loop",
            "sandbox_watchdog_loop",
            "warm_pool_maintain_loop",
            "run_startup_tasks",
        }
    )

    def safe_create_task(coro, **kwargs):
        """Wrap create_task: close known background coroutines, schedule the rest."""
        if asyncio.iscoroutine(coro):
            name = getattr(coro, "__qualname__", "") or ""
            if any(bg in name for bg in _BACKGROUND_CORO_NAMES):
                # Closing an AsyncMock-created coroutine is the only reliable
                # disposal path under Python 3.12+; injecting GeneratorExit
                # leaves its internal awaitable warning at interpreter teardown.
                with contextlib.suppress(RuntimeError):
                    coro.close()
                # Lifespans retain these task handles and await them during
                # shutdown. Return a completed Future, not a bare mock, so
                # tests preserve the production task contract while keeping
                # long-running maintenance loops out of unit tests.
                try:
                    completed = asyncio.get_running_loop().create_future()
                except RuntimeError:
                    return MagicMock()
                completed.set_result(None)
                return completed
        try:
            asyncio.get_running_loop()
            return original_create_task(coro, **kwargs)
        except RuntimeError:
            if asyncio.iscoroutine(coro):
                coro.close()
            return MagicMock()

    mock_broadcast_event = AsyncMock(return_value=None)

    mock_emit_sync = MagicMock()
    mock_cache_loop = AsyncMock(return_value=None)
    mock_periodic_loop = AsyncMock(return_value=None)
    with (
        patch("spectra_mission.core.websocket.manager.broadcast", mock_broadcast),
        patch("spectra_mission.core.websocket.manager.broadcast_event", mock_broadcast_event),
        patch("spectra_infra.events.EventBus.emit_sync", mock_emit_sync),
        patch("spectra_infra.background_tasks.cache_cleanup_loop", mock_cache_loop),
        patch("spectra_infra.background_tasks.periodic_cleanup_loop", mock_periodic_loop),
        patch("asyncio.create_task", safe_create_task),
    ):
        yield


@pytest.fixture(autouse=True)
def disable_rate_limiting_for_unit_tests(request):
    """Disable slowapi rate limiting in unit tests to prevent 429 errors."""
    if _is_live_test(request.node):
        yield
        return
    from spectra_auth.rate_limit import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def mock_llm_for_unit_tests(request):
    """
    Provide mock LLM client for unit tests.

    The mock LLM client was removed from the production app — it now
    lives in tests/mocks/llm.py and is injected here.
    """
    if _is_live_test(request.node):
        yield
        return

    from tests.mocks.llm import MockLLMClient

    mock_instance = MockLLMClient()

    def patched_get_llm_client(provider: str = "tensorzero", **kwargs):
        return mock_instance

    def patched_get_default_llm_client():
        return mock_instance

    with (
        patch("spectra_ai_core.llm.get_llm_client", patched_get_llm_client),
        patch("spectra_ai_core.llm.get_default_llm_client", patched_get_default_llm_client),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_database_for_unit_tests(request):
    """
    Mock database session for unit tests only.

    Live tests bypass this to use real database connections.
    """
    # Skip mocking for live tests
    if _is_live_test(request.node):
        yield
        return

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()  # sync method

    # AsyncSession.execute() returns a synchronous Result object. Returning a
    # bare AsyncMock here turns ``(await execute()).mappings().all()`` into an
    # un-awaited coroutine, hiding integration mistakes in authentication and
    # repository tests.
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    # Create an async context manager
    class MockSessionMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    with patch("spectra_persistence.database.async_session_maker", MockSessionMaker()):
        yield mock_session


@pytest_asyncio.fixture(autouse=True)
async def reset_token_blacklist_for_unit_tests(request, mock_database_for_unit_tests):
    """Give each unit test loop-local, empty JWT revocation state.

    The production cache deliberately lives for the process lifetime. Pytest
    uses a new asyncio loop per test, so retaining its Lock/Event instances
    makes otherwise unrelated token tests order-dependent and can bind the
    next test to a closed loop. The persistence mock supplies the authoritative
    empty state for each test, preserving the fail-closed production path.
    """
    if _is_live_test(request.node):
        yield
        return

    import spectra_auth.security as security

    security._blacklisted_tokens.clear()
    security._user_token_blacklist.clear()
    security._blacklist_lock = asyncio.Lock()
    security._blacklist_ready = asyncio.Event()
    security._blacklist_load_started = False
    security._cleanup_counter = 0
    yield


@pytest_asyncio.fixture
async def mission_manager(mock_websocket_for_unit_tests, mock_database_for_unit_tests):
    """
    Provide a MissionManager instance for tests.

    For live tests, this returns a real instance (via real_mission_manager).
    For unit/integration tests, it returns an instance with mocked dependencies.
    """
    from spectra_mission.manager import MissionManager
    from tests.mocks.llm import MockLLMClient

    # If it's a live test, we should ideally use real_mission_manager,
    # but pytest fixtures don't easily allow conditional switching based on markers
    # inside the fixture itself without request.node inspection which is complex with async.
    # Instead, we'll rely on the fact that live tests should request 'real_mission_manager' explicitly
    # or we can try to detect it.

    # For now, we return a standard manager.
    # The autouse mocks (mock_websocket, mock_database) will handle the patching
    # if it's NOT a live test.

    manager = MissionManager()

    # Initialize agents with a mock LLM to avoid None errors in tests
    mock_llm = MockLLMClient()
    from spectra_ai_core.agents.mission_controller import MissionController
    from spectra_ai_core.agents.scope import ScopeAgent
    from spectra_ai_core.consensus import VotingSystem
    from spectra_mission.executor import MissionExecutor

    manager.execution.mission_controller = MissionController(mock_llm)
    manager.execution.scope_agent = ScopeAgent(mock_llm)
    manager.execution.executor = MissionExecutor(mock_llm)
    manager.execution.consensus = VotingSystem(mock_llm)
    manager._agents_initialized = True

    yield manager


@pytest.fixture(autouse=True)
def reset_service_singletons():
    """Reset service singletons and caches between tests to prevent state leakage."""
    yield
    try:
        import spectra_ai_core.exploit_db as _edb_mod

        _edb_mod._instance = None
    except Exception:
        pass
    try:
        import spectra_ai_core.cve_intel as _cve_mod

        _cve_mod._cve_knowledge_base = None
        _cve_mod._last_nvd_request = 0.0
    except Exception:
        pass


@pytest.fixture
def test_target_ip():
    """Return a test target IP."""
    return "192.168.1.100"


@pytest.fixture(autouse=True)
def mock_storage_for_unit_tests(request):
    """Mock the storage service for unit tests.

    S3 is required in production but unit tests should not need a running S3.
    Live/integration tests bypass this fixture.
    """
    if _is_live_test(request.node):
        yield
        return

    mock_storage = MagicMock()
    mock_storage.is_s3 = True
    mock_storage.upload = AsyncMock(return_value="s3://bucket/key")
    mock_storage.upload_file = AsyncMock(return_value="s3://bucket/key")
    mock_storage.download = AsyncMock(return_value=b"")
    mock_storage.download_file = AsyncMock(return_value="/tmp/file")
    mock_storage.delete = AsyncMock(return_value=True)
    mock_storage.exists = AsyncMock(return_value=False)
    mock_storage.list_objects = AsyncMock(return_value=[])
    mock_storage.get_presigned_url = AsyncMock(return_value=None)
    mock_storage.copy = AsyncMock(return_value=True)
    mock_storage.health_check = AsyncMock(return_value={"status": "healthy", "mode": "s3"})
    mock_storage.close = AsyncMock()

    with patch("spectra_storage_policy.storage.service._storage_service", mock_storage):
        yield mock_storage
