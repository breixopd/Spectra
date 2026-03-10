"""HTTP client for external sandbox orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from app.services.gateway.http_client import GatewayClient

logger = logging.getLogger("spectra.gateway.sandbox")


class SandboxOrchestratorClient:
    """Routes sandbox operations to an external orchestrator via HTTP."""

    def __init__(self, base_url: str, *, timeout: int = 30, api_key: str = ""):
        self._client = GatewayClient(base_url, timeout=timeout, api_key=api_key)

    @property
    def available(self) -> bool:
        return True

    async def create(
        self,
        mission_id: str,
        *,
        resource_tier: str = "medium",
        user_id: str | None = None,
    ) -> dict:
        return await self._client.post(
            "/v1/sandboxes",
            json={
                "mission_id": mission_id,
                "resource_tier": resource_tier,
                "user_id": user_id,
            },
        )

    async def destroy(self, mission_id: str) -> None:
        await self._client.delete(f"/v1/sandboxes/{mission_id}")

    async def get(self, mission_id: str) -> dict | None:
        try:
            return await self._client.get(f"/v1/sandboxes/{mission_id}")
        except Exception:
            return None

    async def exec_command(self, mission_id: str, command: str, **kwargs: Any) -> dict:
        return await self._client.post(
            f"/v1/sandboxes/{mission_id}/exec",
            json={"command": command, **kwargs},
        )

    async def health_check(self) -> dict:
        return await self._client.health_check()

    async def close(self) -> None:
        await self._client.close()
