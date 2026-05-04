"""Tests for sandbox orchestrator client."""

import pytest

from spectra_platform.services.gateway.sandbox_orchestrator import SandboxOrchestratorClient


@pytest.fixture
def client():
    return SandboxOrchestratorClient("http://test", api_key="key")


def test_client_available(client):
    assert client.available is True


@pytest.mark.asyncio
async def test_client_create_posts_to_gateway(client, monkeypatch):
    calls = []

    async def fake_post(path, json=None):
        calls.append((path, json))
        return {"id": "sandbox-1"}

    monkeypatch.setattr(client._client, "post", fake_post)
    result = await client.create("mission-1", resource_tier="high", user_id="user-1")
    assert result == {"id": "sandbox-1"}
    assert calls[0] == (
        "/v1/sandboxes",
        {"mission_id": "mission-1", "resource_tier": "high", "user_id": "user-1"},
    )


@pytest.mark.asyncio
async def test_client_destroy_deletes_from_gateway(client, monkeypatch):
    calls = []

    async def fake_delete(path):
        calls.append(path)

    monkeypatch.setattr(client._client, "delete", fake_delete)
    await client.destroy("mission-1")
    assert calls == ["/v1/sandboxes/mission-1"]


@pytest.mark.asyncio
async def test_client_get_returns_data(client, monkeypatch):
    async def fake_get(path):
        return {"status": "running"}

    monkeypatch.setattr(client._client, "get", fake_get)
    result = await client.get("mission-1")
    assert result == {"status": "running"}


@pytest.mark.asyncio
async def test_client_get_returns_none_on_error(client, monkeypatch):
    async def fake_get(path):
        raise ConnectionError("boom")

    monkeypatch.setattr(client._client, "get", fake_get)
    result = await client.get("mission-1")
    assert result is None


@pytest.mark.asyncio
async def test_client_exec_posts_command(client, monkeypatch):
    calls = []

    async def fake_post(path, json=None):
        calls.append((path, json))
        return {"output": "ok"}

    monkeypatch.setattr(client._client, "post", fake_post)
    result = await client.exec_command("mission-1", "ls -la", env={"X": "1"})
    assert result == {"output": "ok"}
    assert calls[0] == (
        "/v1/sandboxes/mission-1/exec",
        {"command": "ls -la", "env": {"X": "1"}},
    )


@pytest.mark.asyncio
async def test_client_health_check_delegates(client, monkeypatch):
    async def fake_health():
        return {"status": "ok"}

    monkeypatch.setattr(client._client, "health_check", fake_health)
    result = await client.health_check()
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_client_close_delegates(client, monkeypatch):
    calls = []

    async def fake_close():
        calls.append("closed")

    monkeypatch.setattr(client._client, "close", fake_close)
    await client.close()
    assert calls == ["closed"]
