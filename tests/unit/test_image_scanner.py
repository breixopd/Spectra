"""Tests for container image vulnerability scanning."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr


class TestImageScanConfig:
    """Image scan config settings."""

    def test_scan_enabled_default_true(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"),
            SANDBOX_IMAGE_SCAN_ENABLED=True,
        )
        assert s.SANDBOX_IMAGE_SCAN_ENABLED is True

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

    def test_unavailable_without_trivy(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value=None):
            scanner = ImageScanner()
            assert scanner.available is False

    def test_available_with_trivy(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value="/usr/bin/trivy"):
            scanner = ImageScanner()
            assert scanner.available is True

    @pytest.mark.asyncio
    async def test_scan_returns_unavailable_without_trivy(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        with patch("shutil.which", return_value=None):
            scanner = ImageScanner()
            result = await scanner.scan("test-image:latest")
            assert result.status == "unavailable"

    @pytest.mark.asyncio
    async def test_scan_parses_trivy_output(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        trivy_output = json.dumps(
            {
                "Results": [
                    {
                        "Target": "test-image",
                        "Type": "os",
                        "Vulnerabilities": [
                            {"VulnerabilityID": "CVE-2024-001", "Severity": "CRITICAL"},
                            {"VulnerabilityID": "CVE-2024-002", "Severity": "HIGH"},
                            {"VulnerabilityID": "CVE-2024-003", "Severity": "MEDIUM"},
                            {"VulnerabilityID": "CVE-2024-004", "Severity": "LOW"},
                        ],
                    }
                ]
            }
        ).encode()

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(trivy_output, b""))
        mock_process.returncode = 1  # Trivy returns 1 when vulns found

        with (
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch("asyncio.wait_for", return_value=(trivy_output, b"")),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()
            # Override _run_trivy directly for clean test
            trivy_data = json.loads(trivy_output)

            async def mock_run_trivy(image_tag):
                return trivy_data

            scanner._run_trivy = mock_run_trivy
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

        trivy_output = {
            "Results": [
                {
                    "Target": "img",
                    "Type": "os",
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-2024-001", "Severity": "CRITICAL"},
                    ],
                }
            ]
        }

        with (
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()

            async def mock_run_trivy(image_tag):
                return trivy_output

            scanner._run_trivy = mock_run_trivy
            result = await scanner.scan("img:latest", block_critical=True)
            assert result.blocked is True
            assert result.critical == 1

    @pytest.mark.asyncio
    async def test_scan_does_not_block_when_no_critical(self):
        from app.services.tools.sandbox.image_scanner import ImageScanner

        trivy_output = {
            "Results": [
                {
                    "Target": "img",
                    "Type": "os",
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-2024-002", "Severity": "HIGH"},
                    ],
                }
            ]
        }

        with (
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch.object(ImageScanner, "_store_result", new_callable=AsyncMock),
        ):
            scanner = ImageScanner()

            async def mock_run_trivy(image_tag):
                return trivy_output

            scanner._run_trivy = mock_run_trivy
            result = await scanner.scan("img:latest", block_critical=True)
            assert result.blocked is False
