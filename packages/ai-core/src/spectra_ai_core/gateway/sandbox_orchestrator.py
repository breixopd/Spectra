"""HTTP client for external sandbox orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import aiohttp

from spectra_ai_core.gateway.http_client import GatewayClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteSandboxInfo:
    """Validated sandbox state returned by the scheduler control plane."""

    container_id: str
    container_name: str
    mission_id: str
    queue_name: str
    status: str
    image: str
    resource_tier: str = "medium"
    network_id: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> RemoteSandboxInfo:
        required = ("container_id", "container_name", "mission_id", "queue_name", "status", "image")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
            raise RuntimeError("Sandbox controller returned an invalid sandbox payload")
        created_at = None
        value = payload.get("created_at")
        if isinstance(value, str):
            try:
                created_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
            except ValueError as exc:
                raise RuntimeError("Sandbox controller returned an invalid creation timestamp") from exc
        network_id = payload.get("network_id")
        return cls(
            container_id=payload["container_id"],
            container_name=payload["container_name"],
            mission_id=payload["mission_id"],
            queue_name=payload["queue_name"],
            status=payload["status"],
            image=payload["image"],
            resource_tier=str(payload.get("resource_tier") or "medium"),
            network_id=network_id if isinstance(network_id, str) else None,
            created_at=created_at,
        )


class SandboxOrchestratorClient:
    """Routes sandbox operations to an external orchestrator via HTTP."""

    def __init__(self, base_url: str, *, timeout: int = 30, api_key: str = "", service_auth: str = ""):
        self._client = GatewayClient(base_url, timeout=timeout, api_key=api_key, service_auth=service_auth)
        self.is_remote = True

    @property
    def available(self) -> bool:
        return True

    async def create(
        self,
        mission_id: str,
        *,
        resource_tier: str = "medium",
        user_id: str | None = None,
        vpn_config_name: str | None = None,
        vpn_config_path: str | None = None,
    ) -> RemoteSandboxInfo:
        if vpn_config_path is not None:
            raise ValueError("Remote sandbox creation accepts a VPN config name, never a filesystem path")
        payload = await self._client.post(
            "/v1/sandboxes",
            json={
                "mission_id": mission_id,
                "resource_tier": resource_tier,
                "user_id": user_id,
                "vpn_config_name": vpn_config_name,
            },
        )
        return RemoteSandboxInfo.from_payload(payload)

    async def destroy(self, mission_id: str) -> None:
        await self._client.delete(f"/v1/sandboxes/{mission_id}")

    async def get(self, mission_id: str) -> RemoteSandboxInfo | None:
        try:
            return RemoteSandboxInfo.from_payload(await self._client.get(f"/v1/sandboxes/{mission_id}"))
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            raise
        except (OSError, RuntimeError, ConnectionError, TimeoutError):
            return None

    async def health_check(self) -> dict:
        return await self._client.get("/v1/sandboxes/health")

    async def close(self) -> None:
        await self._client.close()
