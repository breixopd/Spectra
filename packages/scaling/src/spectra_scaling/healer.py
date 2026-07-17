"""Automated service recovery with multi-step diagnostics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from spectra_scaling.backends import OrchestratorBackend
from spectra_scaling.config import AutoScalerConfig
from spectra_scaling.notifiers import ScalingNotifier

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    """Outcome of a diagnose-and-heal cycle for a single service."""

    timestamp: str
    service: str
    issue: str
    checks_performed: list[dict] = field(default_factory=list)
    recovery_attempted: list[dict] = field(default_factory=list)
    resolved: bool = False
    summary: str = ""


class ServiceHealer:
    """Multi-step diagnostic and recovery for failed services."""

    def __init__(
        self,
        backend: OrchestratorBackend,
        notifier: ScalingNotifier,
        config: AutoScalerConfig | None = None,
    ) -> None:
        self.backend = backend
        self.notifier = notifier
        self.config = config
        self._heal_history: list[DiagnosticResult] = []
        self._consecutive_failures: dict[str, int] = {}

    async def diagnose_and_heal(self, service: str, issue: str = "unhealthy") -> DiagnosticResult:
        """Run diagnostics and attempt progressive recovery for a service."""
        result = DiagnosticResult(
            timestamp=datetime.now(UTC).isoformat(),
            service=service,
            issue=issue,
        )

        # Step 1: Collect diagnostics
        log_output = await self._collect_service_logs(service)
        result.checks_performed.append({
            "name": "service_logs",
            "result": "collected" if log_output else "unavailable",
            "detail": log_output[:500] if log_output else "No logs available",
        })

        dep_checks = await self._check_dependencies()
        result.checks_performed.extend(dep_checks)

        resource_checks = await self._check_resources()
        result.checks_performed.extend(resource_checks)

        # Step 2: Attempt progressive recovery
        # Step 2a: Force-restart the service
        try:
            restart_result = await self.backend.restart(service)
            success = restart_result.success
            result.recovery_attempted.append({
                "action": "force_restart",
                "success": success,
                "detail": f"Restart {'succeeded' if success else 'failed'}",
            })
            if success:
                result.resolved = True
                result.summary = "Resolved by force-restart"
                self._consecutive_failures[service] = 0
                self._heal_history.append(result)
                return result
        except Exception as exc:
            result.recovery_attempted.append({
                "action": "force_restart",
                "success": False,
                "detail": str(exc),
            })

        # Step 2b: Check if resources are exhausted
        resource_exhausted = any(
            c.get("result") == "critical"
            for c in resource_checks
        )
        result.recovery_attempted.append({
            "action": "resource_check",
            "success": not resource_exhausted,
            "detail": "Resources exhausted" if resource_exhausted else "Resources OK",
        })

        # Step 2c: Check dependencies (DB, Redis)
        deps_healthy = all(
            c.get("result") == "healthy"
            for c in dep_checks
        )
        result.recovery_attempted.append({
            "action": "dependency_check",
            "success": deps_healthy,
            "detail": "All dependencies healthy" if deps_healthy else "Dependency issues detected",
        })

        # Step 2d: If all else fails — collect diagnostic bundle and notify admin
        self._consecutive_failures[service] = self._consecutive_failures.get(service, 0) + 1
        failures = self._consecutive_failures[service]

        diag_bundle = self._build_diagnostic_summary(result)
        result.recovery_attempted.append({
            "action": "admin_notification",
            "success": True,
            "detail": f"Diagnostic bundle sent after {failures} consecutive failures",
        })

        result.resolved = False
        result.summary = (
            f"Recovery failed after {len(result.recovery_attempted)} steps. "
            f"Consecutive failures: {failures}. Admin notified."
        )

        await self.notifier.notify(
            f"Service Recovery Failed: {service}",
            diag_bundle,
            level="critical",
        )

        self._heal_history.append(result)
        return result

    async def _check_dependencies(self) -> list[dict]:
        """Check if DB, Redis, and other dependencies are healthy."""
        checks: list[dict] = []

        # Check PostgreSQL
        try:
            from spectra_persistence.database import engine

            if engine is None:
                checks.append({"name": "postgresql", "result": "unhealthy", "detail": "Database URL not configured"})
            else:
                async with engine.connect() as conn:
                    from sqlalchemy import text
                    await conn.execute(text("SELECT 1"))
                checks.append({"name": "postgresql", "result": "healthy", "detail": "Connection OK"})
        except Exception as exc:
            checks.append({"name": "postgresql", "result": "unhealthy", "detail": str(exc)})

        # Check Redis
        try:
            from spectra_infra.redis_client import RedisCache

            if not await RedisCache().ping():
                raise RuntimeError("Redis is unavailable")
            checks.append({"name": "redis", "result": "healthy", "detail": "PING OK"})
        except Exception as exc:
            checks.append({"name": "redis", "result": "unhealthy", "detail": str(exc)})

        return checks

    async def _check_resources(self) -> list[dict]:
        """Check cluster resource pressure (memory, disk)."""
        checks: list[dict] = []

        try:
            import psutil

            mem = psutil.virtual_memory()
            if mem.percent > 95:
                checks.append({"name": "memory", "result": "critical", "detail": f"{mem.percent:.1f}% used"})
            elif mem.percent > 85:
                checks.append({"name": "memory", "result": "warning", "detail": f"{mem.percent:.1f}% used"})
            else:
                checks.append({"name": "memory", "result": "ok", "detail": f"{mem.percent:.1f}% used"})

            disk = psutil.disk_usage("/")
            free_gb = disk.free / (1024 ** 3)
            if free_gb < 5:
                checks.append({"name": "disk", "result": "critical", "detail": f"{free_gb:.1f}GB free"})
            elif free_gb < 10:
                checks.append({"name": "disk", "result": "warning", "detail": f"{free_gb:.1f}GB free"})
            else:
                checks.append({"name": "disk", "result": "ok", "detail": f"{free_gb:.1f}GB free"})
        except Exception as exc:
            checks.append({"name": "system_resources", "result": "error", "detail": str(exc)})

        return checks

    async def _collect_service_logs(self, service: str, lines: int = 50) -> str:
        """Get recent logs from a service for diagnostics."""
        try:
            from spectra_scaling.docker_client import get_service_logs
            return await get_service_logs(service, tail=lines)
        except Exception as exc:
            logger.debug("Failed to collect logs for %s: %s", service, exc)
            return ""

    def get_heal_history(self, limit: int = 50) -> list[dict]:
        """Return recent healing events as serializable dicts."""
        recent = self._heal_history[-limit:]
        return [
            {
                "timestamp": r.timestamp,
                "service": r.service,
                "issue": r.issue,
                "checks_performed": r.checks_performed,
                "recovery_attempted": r.recovery_attempted,
                "resolved": r.resolved,
                "summary": r.summary,
            }
            for r in recent
        ]

    @staticmethod
    def _build_diagnostic_summary(result: DiagnosticResult) -> str:
        """Build a human-readable diagnostic report for admin notification."""
        lines = [
            f"Service: {result.service}",
            f"Issue: {result.issue}",
            f"Time: {result.timestamp}",
            "",
            "Checks:",
        ]
        for check in result.checks_performed:
            lines.append(f"  - {check['name']}: {check['result']} — {check.get('detail', '')}")

        lines.append("")
        lines.append("Recovery Attempts:")
        for attempt in result.recovery_attempted:
            status = "OK" if attempt["success"] else "FAILED"
            lines.append(f"  - {attempt['action']}: {status} — {attempt.get('detail', '')}")

        return "\n".join(lines)
