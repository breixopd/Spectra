from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_platform.services.tools.sandbox.image_scanner import ImageScanner, ScanResult


def test_scan_result_to_dict():
    result = ScanResult(
        image="test:latest",
        status="critical",
        critical=2,
        high=1,
        medium=3,
        low=5,
        total=11,
        blocked=True,
        error=None,
        raw_results=[{"id": "CVE-1", "severity": "CRITICAL"}],
    )
    d = result.to_dict()
    assert d["image"] == "test:latest"
    assert d["status"] == "critical"
    assert d["vulnerabilities"]["critical"] == 2
    assert d["blocked"] is True


def test_scan_result_default_scanned_at():
    result = ScanResult(image="test", status="clean")
    assert result.scanned_at is not None


def test_image_scanner_not_available():
    with patch("shutil.which", return_value=None):
        scanner = ImageScanner()
        assert scanner.available is False


def test_image_scanner_available():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()
        assert scanner.available is True


@pytest.mark.asyncio
async def test_scan_unavailable():
    with patch("shutil.which", return_value=None):
        scanner = ImageScanner()
        result = await scanner.scan("test:latest")
        assert result.status == "unavailable"
        assert "Grype not installed" in result.error


@pytest.mark.asyncio
async def test_scan_clean():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()
        with patch.object(scanner, "_run_grype", new_callable=AsyncMock, return_value={"matches": []}):
            with patch.object(scanner, "_store_result", new_callable=AsyncMock):
                result = await scanner.scan("test:latest")
        assert result.status == "clean"
        assert result.total == 0


@pytest.mark.asyncio
async def test_scan_critical_blocked():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()
        grype_output = {
            "matches": [
                {"vulnerability": {"id": "CVE-1", "severity": "Critical"}},
                {"vulnerability": {"id": "CVE-2", "severity": "High"}},
            ]
        }
        with patch.object(scanner, "_run_grype", new_callable=AsyncMock, return_value=grype_output):
            with patch.object(scanner, "_store_result", new_callable=AsyncMock):
                result = await scanner.scan("test:latest", block_critical=True)
        assert result.status == "critical"
        assert result.critical == 1
        assert result.high == 1
        assert result.blocked is True


@pytest.mark.asyncio
async def test_scan_warnings():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()
        grype_output = {
            "matches": [
                {"vulnerability": {"id": "CVE-1", "severity": "High"}},
                {"vulnerability": {"id": "CVE-2", "severity": "Medium"}},
            ]
        }
        with patch.object(scanner, "_run_grype", new_callable=AsyncMock, return_value=grype_output):
            with patch.object(scanner, "_store_result", new_callable=AsyncMock):
                result = await scanner.scan("test:latest")
        assert result.status == "warnings"
        assert result.high == 1
        assert result.medium == 1


@pytest.mark.asyncio
async def test_scan_error():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()
        with patch.object(scanner, "_run_grype", new_callable=AsyncMock, side_effect=RuntimeError("grype failed")):
            result = await scanner.scan("test:latest")
        assert result.status == "error"
        assert "grype failed" in result.error


@pytest.mark.asyncio
async def test_get_last_scan_found():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()

    mock_row = MagicMock()
    mock_row.value = {"image": "test", "status": "clean"}

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_platform.core.database.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
        result = await scanner.get_last_scan()

    assert result == {"image": "test", "status": "clean"}


@pytest.mark.asyncio
async def test_get_last_scan_not_found():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_platform.core.database.async_session_maker", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock(return_value=False))):
        result = await scanner.get_last_scan()

    assert result is None


@pytest.mark.asyncio
async def test_get_last_scan_exception():
    with patch("shutil.which", return_value="/usr/bin/grype"):
        scanner = ImageScanner()

    with patch("spectra_platform.core.database.async_session_maker", side_effect=RuntimeError("db error")):
        result = await scanner.get_last_scan()

    assert result is None
