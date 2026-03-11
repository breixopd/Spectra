"""Tests for worker retry logic and helpers."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.worker.helpers import with_retry


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
        with patch("app.worker.helpers.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RuntimeError):
                await job()
        assert sleep_calls == [2.0, 4.0, 8.0]  # 2^1, 2^2, 2^3 (last attempt doesn't sleep)
