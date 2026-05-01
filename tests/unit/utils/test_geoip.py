from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_platform.utils.geoip import GeoLocation, _is_private_ip, resolve_batch, resolve_ip


def test_is_private_ip_localhost():
    assert _is_private_ip("127.0.0.1") is True


def test_is_private_ip_private_range():
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("172.16.0.1") is True


def test_is_private_ip_public():
    assert _is_private_ip("8.8.8.8") is False


def test_is_private_ip_invalid():
    assert _is_private_ip("not-an-ip") is False


@pytest.mark.asyncio
async def test_resolve_ip_localhost():
    result = await resolve_ip("127.0.0.1")
    assert result == GeoLocation(lat=0.0, lon=0.0, city="Localhost", country="Local", region=None, isp=None)


@pytest.mark.asyncio
async def test_resolve_ip_private():
    result = await resolve_ip("192.168.1.1")
    assert result is not None
    assert result["city"] == "Localhost"


@pytest.mark.asyncio
async def test_resolve_ip_domain_name_skipped():
    result = await resolve_ip("example.com")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_ip_success():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "success": True,
        "latitude": 51.5,
        "longitude": -0.1,
        "city": "London",
        "country": "UK",
        "region": "England",
        "connection": {"isp": "TestISP"},
    })

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))

    with patch("spectra_platform.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")

    assert result is not None
    assert result["city"] == "London"
    assert result["country"] == "UK"
    assert result["lat"] == 51.5
    assert result["isp"] == "TestISP"


@pytest.mark.asyncio
async def test_resolve_ip_api_failure():
    mock_response = MagicMock()
    mock_response.status = 500
    mock_response.json = AsyncMock(return_value={})

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))

    with patch("spectra_platform.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_ip_rate_limit():
    mock_response = MagicMock()
    mock_response.status = 429

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))

    with patch("spectra_platform.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_batch():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "success": True,
        "latitude": 40.7,
        "longitude": -74.0,
        "city": "NYC",
        "country": "US",
    })

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))

    with patch("spectra_platform.utils.geoip._session", mock_session):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await resolve_batch(["8.8.8.8", "127.0.0.1"], delay=0)

    assert results["127.0.0.1"]["city"] == "Localhost"
    assert results["8.8.8.8"]["city"] == "NYC"
