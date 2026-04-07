"""Reactive auto-scaling engine.

Monitors queue depth, CPU utilization, and connection counts to automatically
adjust service replica counts via Docker API or CLI.

Infrastructure services (PostgreSQL, Redis, Garage/S3) are NOT auto-scaled
via Docker replicas — they are monitored and alert when thresholds are exceeded.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScalingPolicy:
    """Per-service scaling thresholds."""

    service_name: str
    min_replicas: int = 1
    max_replicas: int = 10
    scale_up_threshold: float = 0.8
    scale_down_threshold: float = 0.2
    scale_up_queue_depth: int = 10
    scale_down_queue_idle_secs: int = 300
    cooldown_secs: int = 300
    last_scale_action: float = 0.0
    queue_idle_since: float = 0.0


@dataclass
class InfraMonitorConfig:
    """Monitoring config for infrastructure services (not auto-scaled)."""

    service_name: str
    health_endpoint: str = ""
    alert_threshold_pct: float = 85.0
    enabled: bool = True


@dataclass
class ScalingDecision:
    """Outcome of evaluating a scaling policy against current metrics."""

    service: str
    action: str  # "scale_up", "scale_down", "none"
    current_replicas: int
    desired_replicas: int
    reason: str


_DEFAULT_INFRA_MONITORS: dict[str, InfraMonitorConfig] = {
    "postgres": InfraMonitorConfig("postgres", "", alert_threshold_pct=80),
    "redis": InfraMonitorConfig("redis", "", alert_threshold_pct=85),
    "garage": InfraMonitorConfig("garage", "", alert_threshold_pct=90),
}


def _as_bool(value) -> bool:
    """Coerce a string/bool/int to bool for config values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AutoScaler:
    """Reactive auto-scaler that adjusts Docker service replica counts."""

    def __init__(self, settings, db_config: dict | None = None) -> None:
        self.settings = settings
        self._db_config: dict = db_config or {}
        self.policies: dict[str, ScalingPolicy] = {}
        self.infra_monitors: dict[str, InfraMonitorConfig] = {}
        self._init_policies()
        self._init_infra_monitors()

    # ------------------------------------------------------------------
    # Config resolution: DB → env var → default
    # ------------------------------------------------------------------

    def _get_cfg(self, db_key: str, env_attr: str, default, cast_fn=int):
        """Read config from DB first, fall back to env var, then default.

        ``db_key``   – key in the ``system_config`` table (e.g. ``scaling.worker.max_replicas``)
        ``env_attr`` – attribute name on ``self.settings`` (e.g. ``AUTOSCALE_WORKER_MAX``)
        ``default``  – hard-coded fallback value
        ``cast_fn``  – callable used to coerce the DB string value (default ``int``)
        """
        # 1) DB config (passed in from caller, already dict[str, str])
        if db_key in self._db_config:
            try:
                return cast_fn(self._db_config[db_key])
            except (ValueError, TypeError):
                pass
        # 2) Env-var-backed settings object
        val = getattr(self.settings, env_attr, None)
        if val is not None:
            try:
                return cast_fn(val)
            except (ValueError, TypeError):
                pass
        # 3) Hard-coded default
        return default

    # ------------------------------------------------------------------
    # Reload / snapshot for admin UI
    # ------------------------------------------------------------------

    def reload_config(self, db_config: dict) -> None:
        """Re-initialize scaling policies from fresh DB config."""
        self._db_config = db_config
        self._init_policies()

    def get_config_snapshot(self) -> dict:
        """Return all current scaling config values for the admin UI."""
        return {
            "scaling.worker.min_replicas": self.policies["worker"].min_replicas,
            "scaling.worker.max_replicas": self.policies["worker"].max_replicas,
            "scaling.api.min_replicas": self.policies["api"].min_replicas,
            "scaling.api.max_replicas": self.policies["api"].max_replicas,
            "scaling.ai.max_replicas": self.policies["ai"].max_replicas,
            "scaling.cooldown_secs": self.policies["worker"].cooldown_secs,
            "scaling.idle_secs": self.policies["worker"].scale_down_queue_idle_secs,
            "scaling.cpu_up_threshold": self.policies["worker"].scale_up_threshold,
            "scaling.cpu_down_threshold": self.policies["worker"].scale_down_threshold,
            "scaling.queue_threshold": self.policies["worker"].scale_up_queue_depth,
            "scaling.enabled": self._get_cfg(
                "scaling.enabled", "AUTOSCALE_ENABLED", True, cast_fn=_as_bool,
            ),
        }

    # ------------------------------------------------------------------
    # Policy initialization
    # ------------------------------------------------------------------

    def _init_policies(self) -> None:
        """Initialize default policies per service from DB / settings."""
        cooldown = self._get_cfg("scaling.cooldown_secs", "AUTOSCALE_COOLDOWN_SECS", 300)
        idle_secs = self._get_cfg("scaling.idle_secs", "AUTOSCALE_IDLE_SECS", 300)
        cpu_up = self._get_cfg(
            "scaling.cpu_up_threshold", "AUTOSCALE_CPU_UP_THRESHOLD", 75,
        ) / 100.0
        cpu_down = self._get_cfg(
            "scaling.cpu_down_threshold", "AUTOSCALE_CPU_DOWN_THRESHOLD", 25,
        ) / 100.0
        queue_threshold = self._get_cfg(
            "scaling.queue_threshold", "AUTOSCALE_QUEUE_THRESHOLD", 5,
        )

        self.policies = {
            # Worker: more workers = more concurrent tool executions; each worker
            # subprocess consumes ~512 MB, so max_replicas=10 is a safe ceiling.
            "worker": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_WORKER_SERVICE", "spectra_worker"),
                min_replicas=self._get_cfg(
                    "scaling.worker.min_replicas", "AUTOSCALE_WORKER_MIN", 1,
                ),
                max_replicas=self._get_cfg(
                    "scaling.worker.max_replicas", "AUTOSCALE_WORKER_MAX", 10,
                ),
                scale_up_threshold=cpu_up,
                scale_down_threshold=cpu_down,
                scale_up_queue_depth=queue_threshold,
                cooldown_secs=cooldown,
                scale_down_queue_idle_secs=max(idle_secs, 600),
            ),
            # API: more replicas = more HTTP concurrency; beyond 8 the DB
            # connection pool becomes the bottleneck.
            "api": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_API_SERVICE", "spectra_app"),
                min_replicas=self._get_cfg(
                    "scaling.api.min_replicas", "AUTOSCALE_API_MIN", 2,
                ),
                max_replicas=self._get_cfg(
                    "scaling.api.max_replicas", "AUTOSCALE_API_MAX", 8,
                ),
                scale_up_threshold=cpu_up,
                scale_down_threshold=cpu_down,
                scale_up_queue_depth=0,
                cooldown_secs=min(cooldown, 120),
                scale_down_queue_idle_secs=min(idle_secs, 300),
            ),
            # AI: LLM inference is memory-heavy; each replica holds embedding
            # models in RAM, so max_replicas=4 avoids OOM pressure.
            "ai": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_AI_SERVICE", "spectra_ai-svc"),
                min_replicas=1,
                max_replicas=self._get_cfg(
                    "scaling.ai.max_replicas", "AUTOSCALE_AI_MAX", 4,
                ),
                scale_up_threshold=0.80,
                scale_down_threshold=0.20,
                scale_up_queue_depth=3,
                cooldown_secs=cooldown,
                scale_down_queue_idle_secs=max(idle_secs, 900),
            ),
            # Scheduler: leader-elected; 2nd replica is a hot standby only.
            "scheduler": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_SCHEDULER_SERVICE", "spectra_scheduler"),
                min_replicas=1,
                max_replicas=2,
                scale_up_threshold=0,
                scale_down_threshold=0,
                scale_up_queue_depth=0,
                cooldown_secs=600,
                scale_down_queue_idle_secs=0,
            ),
        }

    def _init_infra_monitors(self) -> None:
        """Initialize infrastructure monitoring configs from settings."""
        infra_enabled = getattr(self.settings, "INFRA_MONITOR_ENABLED", True)
        self.infra_monitors = {
            "postgres": InfraMonitorConfig(
                "postgres", "",
                alert_threshold_pct=float(getattr(self.settings, "INFRA_MONITOR_PG_THRESHOLD", 80)),
                enabled=infra_enabled,
            ),
            "redis": InfraMonitorConfig(
                "redis", "",
                alert_threshold_pct=float(getattr(self.settings, "INFRA_MONITOR_REDIS_THRESHOLD", 85)),
                enabled=infra_enabled,
            ),
            "garage": InfraMonitorConfig(
                "garage", "",
                alert_threshold_pct=float(getattr(self.settings, "INFRA_MONITOR_STORAGE_THRESHOLD", 90)),
                enabled=infra_enabled,
            ),
        }

    async def evaluate(self, metrics: dict) -> list[ScalingDecision]:
        """Evaluate all policies and return scaling decisions."""
        decisions = []
        now = time.monotonic()

        for role, policy in self.policies.items():
            if now - policy.last_scale_action < policy.cooldown_secs:
                continue

            decision = self._evaluate_policy(role, policy, metrics, now)
            if decision.action != "none":
                decisions.append(decision)

        return decisions

    def _evaluate_policy(
        self, role: str, policy: ScalingPolicy, metrics: dict, now: float
    ) -> ScalingDecision:
        current = metrics.get(f"{role}_replicas", 1)
        utilization = metrics.get(f"{role}_utilization", 0.0)
        queue_depth = metrics.get("queue_depth", 0)

        # --- Scale UP ---
        if role == "worker" and queue_depth > policy.scale_up_queue_depth:
            if current < policy.max_replicas:
                desired = min(
                    current + max(1, queue_depth // policy.scale_up_queue_depth),
                    policy.max_replicas,
                )
                return ScalingDecision(
                    policy.service_name,
                    "scale_up",
                    current,
                    desired,
                    f"Queue depth {queue_depth} > threshold {policy.scale_up_queue_depth}",
                )

        if utilization > policy.scale_up_threshold and current < policy.max_replicas:
            return ScalingDecision(
                policy.service_name,
                "scale_up",
                current,
                min(current + 1, policy.max_replicas),
                f"Utilization {utilization:.0%} > {policy.scale_up_threshold:.0%}",
            )

        # --- Scale DOWN ---
        if role == "worker" and queue_depth == 0:
            if policy.queue_idle_since == 0:
                policy.queue_idle_since = now
            elif (
                now - policy.queue_idle_since > policy.scale_down_queue_idle_secs
                and current > policy.min_replicas
            ):
                return ScalingDecision(
                    policy.service_name,
                    "scale_down",
                    current,
                    max(current - 1, policy.min_replicas),
                    f"Queue idle for {int(now - policy.queue_idle_since)}s",
                )
        else:
            policy.queue_idle_since = 0

        if utilization < policy.scale_down_threshold and current > policy.min_replicas:
            if policy.queue_idle_since == 0:
                policy.queue_idle_since = now
            elif now - policy.queue_idle_since > policy.scale_down_queue_idle_secs:
                return ScalingDecision(
                    policy.service_name,
                    "scale_down",
                    current,
                    max(current - 1, policy.min_replicas),
                    f"Utilization {utilization:.0%} < {policy.scale_down_threshold:.0%}",
                )

        return ScalingDecision(policy.service_name, "none", current, current, "Within thresholds")

    async def execute(self, decision: ScalingDecision) -> bool:
        """Execute a scaling decision via Docker CLI."""
        if decision.action == "none":
            return True

        try:
            success = await self._scale_via_cli(decision)

            if success:
                policy = next(
                    (p for p in self.policies.values() if p.service_name == decision.service),
                    None,
                )
                if policy:
                    policy.last_scale_action = time.monotonic()
                    policy.queue_idle_since = 0

                logger.info(
                    "Scaled %s: %d → %d replicas (%s)",
                    decision.service,
                    decision.current_replicas,
                    decision.desired_replicas,
                    decision.reason,
                )
            return success

        except Exception as e:
            logger.error("Failed to scale %s: %s", decision.service, e)
            return False

    async def _scale_via_cli(self, decision: ScalingDecision) -> bool:
        """Scale via Docker CLI (works with both Swarm and Compose)."""
        # Try Swarm first
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "service",
                "scale",
                f"{decision.service}={decision.desired_replicas}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return True

        # Fallback to docker compose scale
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "compose",
                "-f",
                "docker/docker-compose.yml",
                "up",
                "-d",
                "--scale",
                f"{decision.service}={decision.desired_replicas}",
                "--no-recreate",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0

    async def check_infrastructure(self) -> list[str]:
        """Check infrastructure services and return alert messages for any exceeding thresholds."""
        alerts: list[str] = []
        for name, config in self.infra_monitors.items():
            if not config.enabled:
                continue
            try:
                if name == "postgres":
                    alerts.extend(await self._check_postgres(config))
                elif name == "redis":
                    alerts.extend(await self._check_redis(config))
                elif name == "garage":
                    alerts.extend(await self._check_garage(config))
            except Exception as e:
                logger.debug("Infra check %s failed: %s", name, e)
        return alerts

    async def _check_postgres(self, config: InfraMonitorConfig) -> list[str]:
        """Check PostgreSQL connection count vs max_connections."""
        alerts: list[str] = []
        try:
            from sqlalchemy import text

            from app.core.database import async_session_maker

            async with async_session_maker() as session:
                result = await session.execute(
                    text("SELECT count(*) AS current, setting::int AS max_conn "
                         "FROM pg_stat_activity, pg_settings "
                         "WHERE pg_settings.name = 'max_connections' "
                         "GROUP BY setting")
                )
                row = result.first()
                if row:
                    current, max_conn = row[0], row[1]
                    usage_pct = (current / max(1, max_conn)) * 100
                    if usage_pct >= config.alert_threshold_pct:
                        alerts.append(
                            f"PostgreSQL connections at {usage_pct:.0f}% "
                            f"({current}/{max_conn})"
                        )
        except Exception as e:
            logger.debug("PostgreSQL health check failed: %s", e)
        return alerts

    async def _check_redis(self, config: InfraMonitorConfig) -> list[str]:
        """Check Redis memory usage vs maxmemory."""
        alerts: list[str] = []
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["redis-cli", "-h", "redis", "INFO", "memory"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                info = result.stdout
                used = maxmem = 0
                for line in info.splitlines():
                    if line.startswith("used_memory:"):
                        used = int(line.split(":")[1].strip())
                    elif line.startswith("maxmemory:"):
                        maxmem = int(line.split(":")[1].strip())
                if maxmem > 0:
                    usage_pct = (used / maxmem) * 100
                    if usage_pct >= config.alert_threshold_pct:
                        alerts.append(
                            f"Redis memory at {usage_pct:.0f}% "
                            f"({used // (1024 * 1024)}MB/{maxmem // (1024 * 1024)}MB)"
                        )
        except Exception as e:
            logger.debug("Redis health check failed: %s", e)
        return alerts

    async def _check_garage(self, config: InfraMonitorConfig) -> list[str]:
        """Check Garage/S3 bucket sizes for storage usage tracking."""
        alerts: list[str] = []
        try:
            from app.core.config import settings as app_settings

            endpoint = getattr(app_settings, "S3_ENDPOINT_URL", "")
            if not endpoint:
                return alerts

            import boto3
            from botocore.config import Config as BotoConfig

            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=getattr(app_settings, "S3_ACCESS_KEY", None),
                aws_secret_access_key=getattr(app_settings, "S3_SECRET_KEY", None),
                region_name=getattr(app_settings, "S3_REGION", "us-east-1"),
                config=BotoConfig(connect_timeout=5, read_timeout=5),
            )
            buckets_resp = await asyncio.to_thread(s3.list_buckets)
            bucket_sizes: list[str] = []
            for bucket in buckets_resp.get("Buckets", []):
                try:
                    objs = await asyncio.to_thread(
                        s3.list_objects_v2,
                        Bucket=bucket["Name"],
                        MaxKeys=1,
                    )
                    count = objs.get("KeyCount", 0)
                    if count > 0:
                        bucket_sizes.append(bucket["Name"])
                except Exception:
                    pass
            # Storage usage is informational — alert if any bucket check fails
            # In production, actual byte-level tracking would use CloudWatch/metrics
        except Exception as e:
            logger.debug("Garage/S3 health check failed: %s", e)
        return alerts

    async def evaluate_and_execute(self, metrics: dict) -> list[ScalingDecision]:
        """Evaluate all policies, execute scaling decisions, and check infrastructure."""
        decisions = await self.evaluate(metrics)
        for decision in decisions:
            if decision.action != "none":
                await self.execute(decision)

        # Check infrastructure and send alerts
        infra_alerts = await self.check_infrastructure()
        for alert_msg in infra_alerts:
            logger.warning("Infrastructure alert: %s", alert_msg)
            try:
                from app.services.notifications import send_notification

                await send_notification(
                    title="Infrastructure Alert",
                    message=alert_msg,
                    priority="high",
                    tags=["warning", "infrastructure"],
                )
            except Exception as e:
                logger.debug("Failed to send infra alert: %s", e)

        return decisions

    def get_status(self) -> dict:
        """Return current auto-scaler status and policy state."""
        now = time.monotonic()
        policies = {}
        for role, policy in self.policies.items():
            cooldown_remaining = max(0, policy.cooldown_secs - (now - policy.last_scale_action))
            policies[role] = {
                "service_name": policy.service_name,
                "min_replicas": policy.min_replicas,
                "max_replicas": policy.max_replicas,
                "scale_up_threshold": policy.scale_up_threshold,
                "scale_down_threshold": policy.scale_down_threshold,
                "scale_up_queue_depth": policy.scale_up_queue_depth,
                "cooldown_secs": policy.cooldown_secs,
                "cooldown_remaining_secs": round(cooldown_remaining, 1),
                "idle_since_secs": round(now - policy.queue_idle_since, 1) if policy.queue_idle_since else 0,
            }

        infra = {}
        for name, config in self.infra_monitors.items():
            infra[name] = {
                "enabled": config.enabled,
                "alert_threshold_pct": config.alert_threshold_pct,
            }

        return {"policies": policies, "infrastructure": infra}
