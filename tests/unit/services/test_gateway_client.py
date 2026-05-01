"""Tests for GatewayClient retry logic."""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import pytest_asyncio

from spectra_platform.services.gateway.http_client import MAX_RETRIES, GatewayClient


@pytest_asyncio.fixture
async def client():
    c = GatewayClient("http://gateway.test", timeout=5, api_key="test-key")
    yield c
    await c.close()


@pytest.mark.asyncio
class TestGatewayClientRequest:
    """Tests for _request retry behaviour."""

    async def test_success_on_first_try(self, client: GatewayClient):
        with patch.object(client, "_do_request", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            result = await client.get("/test")
        assert result == {"ok": True}
        mock.assert_awaited_once()

    async def test_retries_on_connection_error_then_succeeds(self, client: GatewayClient):
        with (
            patch.object(client, "_do_request", new_callable=AsyncMock) as mock,
            patch("spectra_platform.services.gateway.http_client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.side_effect = [aiohttp.ClientConnectionError("fail"), {"ok": True}]
            result = await client.get("/test")
        assert result == {"ok": True}
        assert mock.await_count == 2

    async def test_retries_on_timeout_then_succeeds(self, client: GatewayClient):
        with (
            patch.object(client, "_do_request", new_callable=AsyncMock) as mock,
            patch("spectra_platform.services.gateway.http_client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.side_effect = [TimeoutError(), TimeoutError(), {"ok": True}]
            result = await client.get("/test")
        assert result == {"ok": True}
        assert mock.await_count == 3

    async def test_gives_up_after_max_retries(self, client: GatewayClient):
        with (
            patch.object(client, "_do_request", new_callable=AsyncMock) as mock,
            patch("spectra_platform.services.gateway.http_client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.side_effect = aiohttp.ClientConnectionError("fail")
            with pytest.raises(aiohttp.ClientConnectionError):
                await client.get("/test")
        assert mock.await_count == MAX_RETRIES

    async def test_retries_on_server_disconnected_then_succeeds(self, client: GatewayClient):
        with (
            patch.object(client, "_do_request", new_callable=AsyncMock) as mock,
            patch("spectra_platform.services.gateway.http_client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.side_effect = [aiohttp.ServerDisconnectedError(), {"ok": True}]
            result = await client.get("/test")
        assert result == {"ok": True}
        assert mock.await_count == 2

    async def test_post_delegates(self, client: GatewayClient):
        with patch.object(client, "_do_request", new_callable=AsyncMock) as mock:
            mock.return_value = {"created": True}
            result = await client.post("/items", json={"name": "x"})
        assert result == {"created": True}
        mock.assert_awaited_once()

    async def test_delete_delegates(self, client: GatewayClient):
        with patch.object(client, "_do_request", new_callable=AsyncMock) as mock:
            mock.return_value = {"deleted": True}
            result = await client.delete("/items/1")
        assert result == {"deleted": True}


@pytest.mark.asyncio
class TestGatewayClientSession:
    """Tests for session/connector setup."""

    async def test_headers_include_api_key(self, client: GatewayClient):
        session = await client._get_session()
        assert session.headers["Authorization"] == "Bearer test-key"
        assert session.headers["Content-Type"] == "application/json"
        await client.close()

    async def test_connector_is_configured(self, client: GatewayClient):
        session = await client._get_session()
        connector = session.connector
        assert isinstance(connector, aiohttp.TCPConnector)
        assert connector._limit == 50
        assert connector._limit_per_host == 10
        await client.close()

    async def test_session_reused(self, client: GatewayClient):
        s1 = await client._get_session()
        s2 = await client._get_session()
        assert s1 is s2
        await client.close()

    async def test_close_clears_session(self, client: GatewayClient):
        await client._get_session()
        assert client._session is not None
        await client.close()
        assert client._session is None
        assert client._connector is None


@pytest.mark.asyncio
class TestGatewayClientHealthCheck:
    """Tests for health_check."""

    async def test_healthy(self, client: GatewayClient):
        with patch.object(client, "get", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "ok"}
            result = await client.health_check()
        assert result == {"status": "ok"}

    async def test_unhealthy(self, client: GatewayClient):
        with patch.object(client, "get", new_callable=AsyncMock) as mock:
            mock.side_effect = ConnectionError("boom")
            result = await client.health_check()
        assert result["status"] == "unhealthy"
        assert "boom" in result["error"]
