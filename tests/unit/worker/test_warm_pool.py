"""Tests for warm pool of pre-warmed sandbox containers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr


class TestWarmPoolConfig:
    """Warm pool config settings."""

    def test_warm_pool_size_default(self):
        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"))
        assert s.SANDBOX_WARM_POOL_SIZE == 2


class TestWarmPoolManager:
    """WarmPoolManager basic tests."""

    def test_import(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

        assert WarmPoolManager is not None

    def test_constants(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

        assert WarmPoolManager.WARM_STATUS == "warm"
        assert WarmPoolManager.WARM_QUEUE_PREFIX == "warm_"

    def test_init_with_pool(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        wm = WarmPoolManager(mock_pool)
        assert wm._pool is mock_pool

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_no_warm_containers(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock()
        wm = WarmPoolManager(mock_pool)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.tools.sandbox.warm_pool.async_session_maker", return_value=mock_session):
            result = await wm.claim("mission-1")
            assert result is None

    @pytest.mark.asyncio
    async def test_maintain_skips_when_pool_unavailable(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

        mock_pool = MagicMock(available=False)
        wm = WarmPoolManager(mock_pool)
        wm._spawn_warm_container = AsyncMock()
        with patch("app.services.tools.sandbox.warm_pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_WARM_POOL_SIZE=2)
            await wm.maintain()
            wm._spawn_warm_container.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_marks_warm_as_destroyed(self):
        from app.services.tools.sandbox.warm_pool import WarmPoolManager

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

        with patch("app.services.tools.sandbox.warm_pool.async_session_maker", return_value=mock_session):
            count = await wm.cleanup()
            assert count == 0


class TestWarmPoolSingleton:
    """Singleton accessors work."""

    def test_get_set_warm_pool_manager(self):
        from app.services.tools.sandbox import get_warm_pool_manager, set_warm_pool_manager

        mock = MagicMock()
        set_warm_pool_manager(mock)  # type: ignore[arg-type]
        assert get_warm_pool_manager() is mock
        set_warm_pool_manager(None)
