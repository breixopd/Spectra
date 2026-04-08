"""Tests for worker retry logic and helpers."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.worker.helpers import with_retry
from tests.helpers import make_module


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        @with_retry(max_retries=3)
        async def job():
            return "ok"

        assert await job() == "ok"

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @with_retry(max_retries=3, backoff_base=0.01)
        async def job():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail")
            return "ok"

        with patch("app.worker.helpers.asyncio.sleep", new_callable=AsyncMock):
            result = await job()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self):
        @with_retry(max_retries=2, backoff_base=0.01)
        async def job():
            raise ValueError("always fails")

        with patch("app.worker.helpers.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="always fails"):
                await job()

    @pytest.mark.asyncio
    async def test_cancelled_error_not_retried(self):
        call_count = 0

        @with_retry(max_retries=3)
        async def job():
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await job()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        @with_retry(max_retries=4, backoff_base=2.0, max_backoff=10.0)
        async def job():
            raise RuntimeError("fail")

        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("app.worker.helpers.asyncio.sleep", side_effect=mock_sleep), pytest.raises(RuntimeError):
            await job()
        assert len(sleep_calls) == 3  # 3 retries before final failure
        # Base delays are 2^1, 2^2, 2^3 plus jitter in [0, 1)
        assert 2.0 <= sleep_calls[0] < 3.0
        assert 4.0 <= sleep_calls[1] < 5.0
        assert 8.0 <= sleep_calls[2] < 9.0


class TestToolStatusHelpers:
    @pytest.mark.asyncio
    async def test_sync_tool_status_preserves_existing_fields_and_appends_log(self):
        from app.worker.helpers import _sync_tool_status

        cache = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "message": "existing message",
                    "phase": "existing phase",
                    "command": "existing command",
                    "last_output": "existing output",
                    "logs": ["old log"],
                }
            ),
            set=AsyncMock(),
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(
                sys.modules,
                "app.core.cache",
                make_module("app.core.cache", CacheService=lambda: cache),
            )
            await _sync_tool_status("demo-tool", {"status": "running", "log_entry": "started"})

        key, payload = cache.set.await_args.args
        assert key == "spectra:tool_status:demo-tool"
        assert payload["status"] == "running"
        assert payload["message"] == "existing message"
        assert payload["phase"] == "existing phase"
        assert payload["command"] == "existing command"
        assert payload["last_output"] == "existing output"
        assert payload["logs"][0] == "old log"
        assert payload["logs"][1].endswith("started")
        assert cache.set.await_args.kwargs["ttl"] == 3600
