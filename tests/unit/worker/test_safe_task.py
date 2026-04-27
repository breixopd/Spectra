"""Unit tests for safe asyncio task creation."""

import asyncio
import logging

import pytest

from app.infrastructure.tasks import create_safe_task


@pytest.mark.asyncio
async def test_safe_task_logs_exception(caplog):
    async def failing():
        raise ValueError("test error")

    with caplog.at_level(logging.ERROR):
        task = create_safe_task(failing(), name="test-fail")
        with pytest.raises(ValueError):
            await task


@pytest.mark.asyncio
async def test_safe_task_success():
    async def succeeding():
        return 42

    task = create_safe_task(succeeding(), name="test-ok")
    result = await task
    assert result == 42


@pytest.mark.asyncio
async def test_safe_task_cancelled():
    async def slow():
        await asyncio.sleep(100)

    task = create_safe_task(slow(), name="test-cancel")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
