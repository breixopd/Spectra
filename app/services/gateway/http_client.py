"""Base HTTP gateway client with retry, timeout, and auth."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger("spectra.gateway")


class GatewayClient:
    """Base HTTP client for communicating with external Spectra services."""

    def __init__(self, base_url: str, *, timeout: int = 30, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(
                timeout=self.timeout, headers=headers
            )
        return self._session

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        async with session.request(method, url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get(self, path: str, **kwargs: Any) -> dict:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict:
        return await self._request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict:
        return await self._request("DELETE", path, **kwargs)

    async def health_check(self) -> dict:
        try:
            return await self.get("/health")
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
