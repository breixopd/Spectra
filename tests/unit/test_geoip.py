"""Tests for the geoip utility module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.geoip import _is_private_ip, resolve_batch, resolve_ip

# ---------------------------------------------------------------------------
# _is_private_ip
# ---------------------------------------------------------------------------


class TestIsPrivateIp:
    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
            "127.0.0.1",
            "127.0.0.2",
        ],
    )
    def test_private_ips(self, ip: str):
        assert _is_private_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "151.101.1.140",
            "93.184.216.34",
        ],
    )
    def test_public_ips(self, ip: str):
        assert _is_private_ip(ip) is False

    def test_invalid_ip(self):
        assert _is_private_ip("not-an-ip") is False

    def test_loopback_ipv6(self):
        assert _is_private_ip("::1") is True


# ---------------------------------------------------------------------------
# resolve_ip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveIp:
    async def test_localhost_returns_local(self):
        result = await resolve_ip("127.0.0.1")
        assert result is not None
        assert result["city"] == "Localhost"
        assert result["country"] == "Local"

    async def test_private_ip_returns_local(self):
        result = await resolve_ip("192.168.1.1")
        assert result is not None
        assert result["city"] == "Localhost"

    async def test_non_ip_returns_none(self):
        result = await resolve_ip("example.com")
        assert result is None

    async def test_resolve_public_ip_success(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "success": True,
                "latitude": 51.5,
                "longitude": -0.13,
                "city": "London",
                "country": "United Kingdom",
                "region": "England",
                "connection": {"isp": "BT"},
            }
        )

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_session_ctx

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.utils.geoip.aiohttp.ClientSession", return_value=mock_client_ctx):
            result = await resolve_ip("8.8.8.8")

        assert result is not None
        assert result["city"] == "London"
        assert result["country"] == "United Kingdom"
        assert result["lat"] == 51.5

    async def test_resolve_api_failure(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"success": False, "message": "reserved range"})

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_session_ctx

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.utils.geoip.aiohttp.ClientSession", return_value=mock_client_ctx):
            result = await resolve_ip("8.8.8.8")

        assert result is None

    async def test_resolve_network_error(self):
        import aiohttp

        with patch(
            "app.utils.geoip.aiohttp.ClientSession",
            side_effect=aiohttp.ClientError("connection refused"),
        ):
            result = await resolve_ip("8.8.8.8")

        assert result is None

    async def test_resolve_rate_limited(self):
        mock_resp = AsyncMock()
        mock_resp.status = 429

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_session_ctx

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.utils.geoip.aiohttp.ClientSession", return_value=mock_client_ctx):
            result = await resolve_ip("8.8.8.8")

        assert result is None


# ---------------------------------------------------------------------------
# resolve_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveBatch:
    async def test_batch_with_private_ips(self):
        results = await resolve_batch(["127.0.0.1", "10.0.0.1"], delay=0)
        assert len(results) == 2
        assert results["127.0.0.1"] is not None
        assert results["127.0.0.1"]["city"] == "Localhost"
        assert results["10.0.0.1"]["city"] == "Localhost"

    async def test_batch_empty(self):
        results = await resolve_batch([], delay=0)
        assert results == {}
