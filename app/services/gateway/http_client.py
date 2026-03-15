"""Base HTTP gateway client with retry, timeout, and auth."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from app.core.constants import HTTP_CLIENT_MAX_RETRIES

logger = logging.getLogger(__name__)

MAX_RETRIES = HTTP_CLIENT_MAX_RETRIES
RETRY_BACKOFF_BASE = 0.5  # seconds


class GatewayClient:
    """Base HTTP client for communicating with external Spectra services."""

    def __init__(self, base_url: str, *, timeout: int = 30, api_key: str = "", service_auth: str = ""):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.api_key = api_key
        self.service_auth = service_auth
        self._session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if self.service_auth:
                headers["X-Service-Auth"] = self.service_auth
            self._connector = aiohttp.TCPConnector(
                limit=50,
                limit_per_host=10,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=headers,
                connector=self._connector,
            )
        return self._session

    async def _do_request(self, method: str, url: str, **kwargs: Any) -> dict:
        session = await self._get_session()
        async with session.request(method, url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}{path}"
        last_error: BaseException | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await self._do_request(method, url, **kwargs)
            except (aiohttp.ClientConnectionError, TimeoutError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Gateway request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        MAX_RETRIES,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
        raise last_error  # type: ignore[misc]

    async def get(self, path: str, **kwargs: Any) -> dict:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict:
        return await self._request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict:
        return await self._request("DELETE", path, **kwargs)

    async def health_check(self) -> dict:
        try:
            return await self.get("/health")
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._connector = None
