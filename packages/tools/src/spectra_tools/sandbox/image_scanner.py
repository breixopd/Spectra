"""Container image vulnerability scanning using Grype."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class ScanResult:
    """Structured vulnerability scan results."""

    def __init__(
        self,
        image: str,
        status: str,  # "clean", "warnings", "critical", "error"
        critical: int = 0,
        high: int = 0,
        medium: int = 0,
        low: int = 0,
        total: int = 0,
        blocked: bool = False,
        error: str | None = None,
        scanned_at: str | None = None,
        raw_results: list[dict[str, Any]] | None = None,
    ):
        self.image = image
        self.status = status
        self.critical = critical
        self.high = high
        self.medium = medium
        self.low = low
        self.total = total
        self.blocked = blocked
        self.error = error
        self.scanned_at = scanned_at or datetime.now(UTC).isoformat()
        self.raw_results = raw_results

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "status": self.status,
            "vulnerabilities": {
                "critical": self.critical,
                "high": self.high,
                "medium": self.medium,
                "low": self.low,
                "total": self.total,
            },
            "blocked": self.blocked,
            "error": self.error,
            "scanned_at": self.scanned_at,
        }


class ImageScanner:
    """Scans Docker images for vulnerabilities using Grype.

    Grype must be installed locally (binary in PATH). If not available,
    scans are skipped gracefully. No external APIs are called — all
    scanning is local using Grype's offline DB (auto-downloaded on first use).
    """

    def __init__(self) -> None:
        self._grype_path = shutil.which("grype")
        if self._grype_path:
            logger.info("ImageScanner: Grype found at %s", self._grype_path)
        else:
            logger.info("ImageScanner: Grype not found — image scanning unavailable")

    @property
    def available(self) -> bool:
        return self._grype_path is not None

    async def scan(self, image_tag: str, *, block_critical: bool = False) -> ScanResult:
        """Scan a Docker image for vulnerabilities.

        Args:
            image_tag: Docker image tag to scan (e.g., "spectra-tools:latest")
            block_critical: If True, set blocked=True when critical CVEs are found

        Returns:
            ScanResult with vulnerability counts and status.
        """
        if not self.available:
            return ScanResult(
                image=image_tag,
                status="unavailable",
                error="Grype not installed",
            )

        try:
            result = await self._run_grype(image_tag)

            # Parse severity counts from Grype output
            critical = high = medium = low = 0
            raw_results = []

            if isinstance(result, dict) and "matches" in result:
                for match in result["matches"]:
                    vuln = match.get("vulnerability", {})
                    severity = vuln.get("severity", "").upper()
                    raw_results.append(
                        {
                            "id": vuln.get("id", ""),
                            "severity": severity,
                        }
                    )
                    if severity == "CRITICAL":
                        critical += 1
                    elif severity == "HIGH":
                        high += 1
                    elif severity == "MEDIUM":
                        medium += 1
                    elif severity == "LOW":
                        low += 1

            total = critical + high + medium + low

            # Determine status
            if critical > 0:
                status = "critical"
            elif high > 0:
                status = "warnings"
            else:
                status = "clean"

            blocked = block_critical and critical > 0

            scan_result = ScanResult(
                image=image_tag,
                status=status,
                critical=critical,
                high=high,
                medium=medium,
                low=low,
                total=total,
                blocked=blocked,
                raw_results=raw_results,
            )

            if blocked:
                logger.warning(
                    "Image %s BLOCKED: %d critical CVEs found",
                    image_tag,
                    critical,
                )
            else:
                logger.info(
                    "Image %s scanned: %d vulns (C:%d H:%d M:%d L:%d)",
                    image_tag,
                    total,
                    critical,
                    high,
                    medium,
                    low,
                )

            # Store in system status
            await self._store_result(scan_result)

            return scan_result

        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Image scan failed for %s: %s", image_tag, exc)
            return ScanResult(
                image=image_tag,
                status="error",
                error=str(exc)[:500],
            )

    async def get_last_scan(self) -> dict[str, Any] | None:
        """Get the last scan result from SystemStatus."""
        try:
            from sqlalchemy import select

            from spectra_persistence.database import async_session_maker
            from spectra_persistence.models.infrastructure import SystemStatus

            async with async_session_maker() as session:
                result = await session.execute(select(SystemStatus).where(SystemStatus.key == "image_scan_result"))
                row = result.scalar_one_or_none()
                if row and isinstance(row.value, dict):
                    return row.value
                return None
        except (OSError, RuntimeError):
            return None

    async def _run_grype(self, image_tag: str) -> dict[str, Any]:
        """Run Grype scan and return parsed JSON output."""
        cmd = [
            self._grype_path,
            image_tag,
            "-o",
            "json",
            "--fail-on",
            "critical",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=600,  # 10 min timeout for large images
        )

        if process.returncode not in (0, 1):  # Grype returns 1 when critical vulns found
            raise RuntimeError(f"Grype exited with code {process.returncode}: {stderr.decode()[:500]}")

        return json.loads(stdout.decode())

    async def _store_result(self, scan_result: ScanResult) -> None:
        """Store scan result in SystemStatus table."""
        try:
            from sqlalchemy import select

            from spectra_persistence.database import async_session_maker
            from spectra_persistence.models.infrastructure import SystemStatus

            async with async_session_maker() as session:
                existing = await session.execute(select(SystemStatus).where(SystemStatus.key == "image_scan_result"))
                row = existing.scalar_one_or_none()
                if row:
                    row.value = scan_result.to_dict()
                else:
                    session.add(SystemStatus(key="image_scan_result", value=scan_result.to_dict()))
                await session.commit()
        except (OSError, RuntimeError) as exc:
            logger.debug("Failed to store scan result: %s", exc)
