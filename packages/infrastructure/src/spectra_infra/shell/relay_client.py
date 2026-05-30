"""Client for worker-owned callback listener control."""

from __future__ import annotations

import httpx

from spectra_common.config import settings


class ShellRelayClient:
    """Control-plane client for listener operations executed by workers."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.WORKER_SERVICE_URL).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
        return {"X-Service-Auth": secret} if secret else {}

    async def start_listener(
        self,
        *,
        session_id: str,
        target: str,
        mission_id: str | None,
        port: int = 0,
        ttl_seconds: int = 900,
    ) -> int:
        payload = {
            "session_id": session_id,
            "target": target,
            "mission_id": mission_id,
            "port": port,
            "ttl_seconds": ttl_seconds,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.base_url}/internal/shell/listeners", json=payload, headers=self._headers)
        response.raise_for_status()
        data = response.json()
        return int(data["port"])

    async def list_listeners(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/internal/shell/listeners", headers=self._headers)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    async def stop_listener(self, session_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(f"{self.base_url}/internal/shell/listeners/{session_id}", headers=self._headers)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True


shell_relay_client = ShellRelayClient()
