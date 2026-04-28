"""Tests for container image vulnerability scanning."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr


class TestImageScanConfig:
    """Image scan policy (block promotion on critical CVEs)."""

    def test_block_critical_default_false(self):
        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"))
        assert s.SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL is False


class TestScanResult:
    """ScanResult data class."""

    def test_to_dict(self):
        from app.services.tools.sandbox.image_scanner import ScanResult

        r = ScanResult(
            image="spectra-tools:latest",
            status="warnings",
            critical=0,
            high=3,
            medium=10,
            low=5,
            total=18,
        )
        d = r.to_dict()
        assert d["image"] == "spectra-tools:latest"
        assert d["status"] == "warnings"
        assert d["vulnerabilities"]["high"] == 3
        assert d["vulnerabilities"]["total"] == 18
        assert d["blocked"] is False

    def test_blocked_flag(self):
        from app.services.tools.sandbox.image_scanner import ScanResult

        r = ScanResult(
            image="img",
            status="critical",
            critical=2,
            blocked=True,
        )
        assert r.blocked is True
        assert r.to_dict()["blocked"] is True


class TestImageScanner:
    """ImageScanner class tests."""

    def test_import(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        assert ImageScanner is not None

    def test_unavailable_without_grype(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value=None):
            scanner = ImageScanner()
            assert scanner.available is False

    def test_available_with_grype(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value="/usr/bin/grype"):
            scanner = ImageScanner()
            assert scanner.available is True

    @pytest.mark.asyncio
    async def test_scan_returns_unavailable_without_grype(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value=None):
            scanner = ImageScanner()
            result = await scanner.scan("test-image:latest")
            assert result.status == "unavailable"

    @pytest.mark.asyncio
    async def test_scan_parses_grype_output(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        grype_output = json.dumps(
            {
                "matches": [
                    {"vulnerability": {"id": "CVE-2024-001", "severity": "Critical"}},
                    {"vulnerability": {"id": "CVE-2024-002", "severity": "High"}},
                    {"vulnerability": {"id": "CVE-2024-003", "severity": "Medium"}},
                    {"vulnerability": {"id": "CVE-2024-004", "severity": "Low"}},
                ]
            }
        ).encode()

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(grype_output, b""))
        mock_process.returncode = 1  # Grype returns 1 when critical vulns found

        with (
            patch("shutil.which", return_value="/usr/bin/grype"),
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch("asyncio.wait_for", return_value=(grype_output, b"")),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()
            # Override _run_grype directly for clean test
            grype_data = json.loads(grype_output)

            async def mock_run_grype(image_tag):
                return grype_data

            scanner._run_grype = mock_run_grype
            result = await scanner.scan("test-image:latest")

            assert result.critical == 1
            assert result.high == 1
            assert result.medium == 1
            assert result.low == 1
            assert result.total == 4
            assert result.status == "critical"

    @pytest.mark.asyncio
    async def test_scan_blocks_when_critical_and_configured(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        grype_output = {
            "matches": [
                {"vulnerability": {"id": "CVE-2024-001", "severity": "Critical"}},
            ]
        }

        with (
            patch("shutil.which", return_value="/usr/bin/grype"),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()

            async def mock_run_grype(image_tag):
                return grype_output

            scanner._run_grype = mock_run_grype
            result = await scanner.scan("img:latest", block_critical=True)
            assert result.blocked is True
            assert result.critical == 1

    @pytest.mark.asyncio
    async def test_scan_does_not_block_when_no_critical(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        grype_output = {
            "matches": [
                {"vulnerability": {"id": "CVE-2024-002", "severity": "High"}},
            ]
        }

        with (
            patch("shutil.which", return_value="/usr/bin/grype"),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()

            async def mock_run_grype(image_tag):
                return grype_output

            scanner._run_grype = mock_run_grype
            result = await scanner.scan("img:latest", block_critical=True)
            assert result.blocked is False
