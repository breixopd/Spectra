"""Async primitives used by scheduler loops (tests patch this module per operation)."""

import asyncio
from typing import Any

__all__ = ["gather", "sleep"]


async def sleep(delay: float) -> None:
    await asyncio.sleep(delay)


async def gather(*aws: Any, return_exceptions: bool = False):
    return await asyncio.gather(*aws, return_exceptions=return_exceptions)
