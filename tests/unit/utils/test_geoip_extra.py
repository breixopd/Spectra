from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from spectra_common.utils.geoip import resolve_batch, resolve_ip


@pytest.mark.asyncio
async def test_resolve_ip_api_error():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"success": False, "message": "not found"})

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)
        )
    )

    with patch("spectra_common.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_ip_client_error():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError("network error"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_ip_timeout():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=TimeoutError("timeout"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_ip_unexpected_error():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=ValueError("unexpected"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        result = await resolve_ip("1.2.3.4")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_batch_error():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None


@pytest.mark.asyncio
async def test_resolve_batch_non_ip():
    mock_session = MagicMock()
    mock_session.closed = False

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["example.com"], delay=0)

    assert results["example.com"] is None
    mock_session.get.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_batch_timeout():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=TimeoutError("timeout"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None


@pytest.mark.asyncio
async def test_resolve_batch_unexpected_error():
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(side_effect=ValueError("unexpected"))

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None


@pytest.mark.asyncio
async def test_resolve_batch_api_failed():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"success": False})

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)
        )
    )

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None


@pytest.mark.asyncio
async def test_resolve_batch_rate_limit():
    mock_response = MagicMock()
    mock_response.status = 429

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)
        )
    )

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None


@pytest.mark.asyncio
async def test_resolve_batch_other_status():
    mock_response = MagicMock()
    mock_response.status = 500

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)
        )
    )

    with patch("spectra_common.utils.geoip._session", mock_session):
        results = await resolve_batch(["8.8.8.8"], delay=0)

    assert results["8.8.8.8"] is None
