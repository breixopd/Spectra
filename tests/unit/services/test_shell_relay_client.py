"""Unit tests for ShellRelayClient (worker listener control-plane)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from spectra_platform.services.shell.relay_client import ShellRelayClient


class _AsyncClientCM:
    """Async context manager that returns ``inner`` from ``__aenter__``."""

    def __init__(self, inner: MagicMock) -> None:
        self._inner = inner

    async def __aenter__(self) -> MagicMock:
        return self._inner

    async def __aexit__(self, *args: object) -> bool:
        return False


@pytest.fixture
def auth_secret() -> MagicMock:
    sec = MagicMock()
    sec.get_secret_value = MagicMock(return_value="unit-test-secret")
    return sec


@pytest.mark.asyncio
async def test_start_listener_posts_and_returns_port(auth_secret: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"port": 4444})
    inner = MagicMock()
    inner.post = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "spectra_platform.services.shell.relay_client.httpx.AsyncClient",
            side_effect=lambda *a, **k: _AsyncClientCM(inner),
        ),
        patch("spectra_platform.services.shell.relay_client.settings.SERVICE_AUTH_SECRET", auth_secret),
    ):
        client = ShellRelayClient(base_url="http://worker-test:5012")
        port = await client.start_listener(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            target="10.0.0.1",
            mission_id="m1",
            port=0,
            ttl_seconds=300,
        )

    assert port == 4444
    inner.post.assert_awaited_once()
    _args, kwargs = inner.post.call_args
    assert kwargs["json"]["session_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert kwargs["json"]["target"] == "10.0.0.1"
    assert kwargs["headers"].get("X-Service-Auth") == "unit-test-secret"


@pytest.mark.asyncio
async def test_list_listeners_returns_list(auth_secret: MagicMock) -> None:
    payload = [{"session_id": "s1", "port": 1}]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=payload)
    inner = MagicMock()
    inner.get = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "spectra_platform.services.shell.relay_client.httpx.AsyncClient",
            side_effect=lambda *a, **k: _AsyncClientCM(inner),
        ),
        patch("spectra_platform.services.shell.relay_client.settings.SERVICE_AUTH_SECRET", auth_secret),
    ):
        client = ShellRelayClient(base_url="http://worker-test:5012")
        out = await client.list_listeners()

    assert out == payload


@pytest.mark.asyncio
async def test_stop_listener_404_returns_false(auth_secret: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    inner = MagicMock()
    inner.delete = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "spectra_platform.services.shell.relay_client.httpx.AsyncClient",
            side_effect=lambda *a, **k: _AsyncClientCM(inner),
        ),
        patch("spectra_platform.services.shell.relay_client.settings.SERVICE_AUTH_SECRET", auth_secret),
    ):
        client = ShellRelayClient(base_url="http://worker-test:5012")
        ok = await client.stop_listener("550e8400-e29b-41d4-a716-446655440000")

    assert ok is False


@pytest.mark.asyncio
async def test_stop_listener_success_returns_true(auth_secret: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()
    inner = MagicMock()
    inner.delete = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "spectra_platform.services.shell.relay_client.httpx.AsyncClient",
            side_effect=lambda *a, **k: _AsyncClientCM(inner),
        ),
        patch("spectra_platform.services.shell.relay_client.settings.SERVICE_AUTH_SECRET", auth_secret),
    ):
        client = ShellRelayClient(base_url="http://worker-test:5012")
        ok = await client.stop_listener("550e8400-e29b-41d4-a716-446655440000")

    assert ok is True


@pytest.mark.asyncio
async def test_start_listener_propagates_http_status_error(auth_secret: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("bad", request=MagicMock(), response=mock_resp),
    )
    inner = MagicMock()
    inner.post = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "spectra_platform.services.shell.relay_client.httpx.AsyncClient",
            side_effect=lambda *a, **k: _AsyncClientCM(inner),
        ),
        patch("spectra_platform.services.shell.relay_client.settings.SERVICE_AUTH_SECRET", auth_secret),
    ):
        client = ShellRelayClient(base_url="http://worker-test:5012")
        with pytest.raises(httpx.HTTPStatusError):
            await client.start_listener(
                session_id="550e8400-e29b-41d4-a716-446655440000",
                target="t",
                mission_id=None,
            )
