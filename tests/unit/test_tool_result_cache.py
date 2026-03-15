"""Tests for app.services.tools.cache.ToolResultCache."""

import hashlib
import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.cache import ToolResultCache

PATCH_SESSION_MAKER = "app.core.database.async_session_maker"


class TestMakeKey:
    def test_deterministic(self):
        cache = ToolResultCache()
        k1 = cache._make_key("nmap", "10.0.0.1", {"flags": "-sV"})
        k2 = cache._make_key("nmap", "10.0.0.1", {"flags": "-sV"})
        assert k1 == k2

    def test_different_for_different_args(self):
        cache = ToolResultCache()
        k1 = cache._make_key("nmap", "10.0.0.1", {"flags": "-sV"})
        k2 = cache._make_key("nmap", "10.0.0.1", {"flags": "-sC"})
        assert k1 != k2

    def test_uses_sha256_prefix(self):
        cache = ToolResultCache()
        key = cache._make_key("nmap", "10.0.0.1")
        assert key.startswith("tool_cache:")
        raw = json.dumps({"tool": "nmap", "target": "10.0.0.1", "args": {}}, sort_keys=True)
        expected_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert key == f"tool_cache:{expected_hash}"

    def test_none_args_same_as_empty(self):
        cache = ToolResultCache()
        k1 = cache._make_key("nmap", "10.0.0.1", None)
        k2 = cache._make_key("nmap", "10.0.0.1", {})
        assert k1 == k2


@pytest.mark.asyncio
class TestCacheGet:
    async def test_cache_hit(self):
        cache = ToolResultCache()
        cached_data = {"findings": [{"port": 80}]}

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, i: json.dumps(cached_data)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            result = await cache.get("nmap", "10.0.0.1")
        assert result == cached_data

    async def test_cache_miss(self):
        cache = ToolResultCache()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            result = await cache.get("nmap", "10.0.0.1")
        assert result is None

    async def test_db_error_returns_none(self):
        cache = ToolResultCache()

        mock_session = AsyncMock()
        mock_session.execute.side_effect = OSError("connection failed")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            result = await cache.get("nmap", "10.0.0.1")
        assert result is None


@pytest.mark.asyncio
class TestCacheSet:
    async def test_set_calls_execute_and_commit(self):
        cache = ToolResultCache()

        mock_session = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            await cache.set("nmap", "10.0.0.1", {"findings": []})

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    async def test_set_with_custom_ttl(self):
        cache = ToolResultCache()

        mock_session = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            await cache.set("nmap", "10.0.0.1", {"findings": []},
                            ttl=timedelta(minutes=30))

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["ttl"] == 1800

    async def test_set_db_error_swallowed(self):
        cache = ToolResultCache()

        mock_session = AsyncMock()
        mock_session.execute.side_effect = OSError("write failed")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION_MAKER, return_value=mock_ctx):
            # Should not raise
            await cache.set("nmap", "10.0.0.1", {"findings": []})
