"""Tests for warm pool of pre-warmed sandbox containers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_resolve_target_warm_pool_size_fallback_when_no_nodes():
    from spectra_platform.services.tools.sandbox import warm_pool as wp

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(return_value=mock_row)

    with patch.object(wp, "async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
        n = await wp.resolve_target_warm_pool_size()
    assert n == wp.WARM_POOL_SINGLE_NODE_FALLBACK


@pytest.mark.asyncio
async def test_resolve_target_warm_pool_size_caps_at_ten():
    from spectra_platform.services.tools.sandbox import warm_pool as wp

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.scalar_one.return_value = 15
    mock_session.execute = AsyncMock(return_value=mock_row)

    with patch.object(wp, "async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
        n = await wp.resolve_target_warm_pool_size()
    assert n == wp.MAX_WARM_POOL_CONTAINERS


class TestWarmPoolManager:
    """WarmPoolManager basic tests."""

    def test_import(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        assert WarmPoolManager is not None

    def test_constants(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        assert WarmPoolManager.WARM_STATUS == "warm"
        assert WarmPoolManager.WARM_QUEUE_PREFIX == "warm_"

    def test_init_with_pool(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        wm = WarmPoolManager(mock_pool)
        assert wm._pool is mock_pool

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_no_warm_containers(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        wm = WarmPoolManager(mock_pool)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("spectra_platform.services.tools.sandbox.warm_pool.async_session_maker", return_value=mock_session):
            result = await wm.claim("mission-1")
            assert result is None

    @pytest.mark.asyncio
    async def test_maintain_skips_when_pool_unavailable(self):
        from spectra_platform.services.tools.sandbox import warm_pool as wp
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock(available=False)
        wm = WarmPoolManager(mock_pool)
        wm._spawn_warm_container = AsyncMock()
        with patch.object(wp, "resolve_target_warm_pool_size", AsyncMock(return_value=2)):
            await wm.maintain()
            wm._spawn_warm_container.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_marks_warm_as_destroyed(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        mock_pool._stop_container = AsyncMock()
        mock_pool._remove_network = AsyncMock()
        wm = WarmPoolManager(mock_pool)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        mock_session.commit = AsyncMock()

        with patch("spectra_platform.services.tools.sandbox.warm_pool.async_session_maker", return_value=mock_session):
            count = await wm.cleanup()
            assert count == 0


class TestWarmPoolSingleton:
    """Singleton accessors work."""

    def test_get_set_warm_pool_manager(self):
        from spectra_platform.services.tools.sandbox import get_warm_pool_manager, set_warm_pool_manager

        mock = MagicMock()
        set_warm_pool_manager(mock)  # type: ignore[arg-type]
        assert get_warm_pool_manager() is mock
        set_warm_pool_manager(None)

    @pytest.mark.asyncio
    async def test_count_warm(self):
        from spectra_platform.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        wm = WarmPoolManager(mock_pool)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[1, 2, 3]))))
        )

        with patch("spectra_platform.services.tools.sandbox.warm_pool.async_session_maker", return_value=mock_session):
            count = await wm._count_warm()
            assert count == 3
