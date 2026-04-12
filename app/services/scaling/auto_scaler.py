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
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.scaling.metrics_collector import ClusterMetrics

logger = logging.getLogger(__name__)

# Module-level scaling history (last 100 actions, survives across evaluate cycles)
_scaling_history: deque[dict] = deque(maxlen=100)


def get_scaling_history() -> list[dict]:
    """Return a copy of recent scaling events."""
    return list(_scaling_history)


def _record_scaling_event(
    service: str,
    action: str,
    from_replicas: int,
    to_replicas: int,
    reason: str,
    success: bool,
) -> None:
    _scaling_history.append({
        "service": service,
        "action": action,
        "from_replicas": from_replicas,
        "to_replicas": to_replicas,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
        "success": success,
    })


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

        ``db_key``   - key in the ``system_config`` table (e.g. ``scaling.worker.max_replicas``)
        ``env_attr`` - attribute name on ``self.settings`` (e.g. ``AUTOSCALE_WORKER_MAX``)
        ``default``  - hard-coded fallback value
        ``cast_fn``  - callable used to coerce the DB string value (default ``int``)
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

    async def evaluate(self, metrics: dict, cluster: ClusterMetrics | None = None) -> list[ScalingDecision]:
        """Evaluate all policies and return scaling decisions."""
        decisions = []
        now = time.monotonic()

        # Extract cluster-wide resource pressure signals
        cluster_alerts: list[str] = []
        cluster_cpu_avg = 0.0
        cluster_mem_max = 0.0
        cluster_disk_min_gb = float("inf")
        cnm = cluster.cluster_node_metrics if cluster else None
        if cnm and cnm.per_node:
            cluster_cpu_avg = cnm.avg_cpu_percent
            mem_values = [n.memory_percent for n in cnm.per_node if n.memory_percent > 0]
            cluster_mem_max = max(mem_values) if mem_values else 0.0
            disk_values = [n.disk_free_gb for n in cnm.per_node if n.disk_free_gb > 0]
            cluster_disk_min_gb = min(disk_values) if disk_values else float("inf")

            # Memory pressure alerts
            if cluster_mem_max > 95:
                cluster_alerts.append(
                    f"EMERGENCY: Node memory at {cluster_mem_max:.1f}% — force scale-up"
                )
            elif cluster_mem_max > 85:
                cluster_alerts.append(
                    f"WARNING: Node memory at {cluster_mem_max:.1f}%"
                )

            # Disk space alerts
            if cluster_disk_min_gb < 5:
                cluster_alerts.append(
                    f"CRITICAL: Disk free {cluster_disk_min_gb:.1f}GB on a node"
                )
            elif cluster_disk_min_gb < 10:
                cluster_alerts.append(
                    f"WARNING: Disk free {cluster_disk_min_gb:.1f}GB on a node"
                )

        for alert in cluster_alerts:
            logger.warning("Cluster resource alert: %s", alert)

        for role, policy in self.policies.items():
            if now - policy.last_scale_action < policy.cooldown_secs:
                continue

            decision = self._evaluate_policy(
                role, policy, metrics, now,
                cluster_cpu_avg=cluster_cpu_avg,
                cluster_mem_max=cluster_mem_max,
            )
            if decision.action != "none":
                decisions.append(decision)

        return decisions

    def _evaluate_policy(
        self, role: str, policy: ScalingPolicy, metrics: dict, now: float,
        *, cluster_cpu_avg: float = 0.0, cluster_mem_max: float = 0.0,
    ) -> ScalingDecision:
        current = metrics.get(f"{role}_replicas", 1)
        utilization = metrics.get(f"{role}_utilization", 0.0)
        queue_depth = metrics.get("queue_depth", 0)

        # --- Emergency scale-up on cluster memory pressure (>95%) ---
        if cluster_mem_max > 95 and role == "worker" and current > policy.min_replicas:
            # Under extreme memory pressure, avoid adding more replicas
            return ScalingDecision(
                policy.service_name,
                "none",
                current,
                current,
                f"Memory emergency ({cluster_mem_max:.0f}%) — holding replicas",
            )

        # --- Cluster CPU-based scale-up (avg across nodes) ---
        if cluster_cpu_avg > 0 and role in ("worker", "api", "ai"):
            cluster_util = cluster_cpu_avg / 100.0
            if cluster_util > policy.scale_up_threshold and current < policy.max_replicas:
                return ScalingDecision(
                    policy.service_name,
                    "scale_up",
                    current,
                    min(current + 1, policy.max_replicas),
                    f"Cluster CPU avg {cluster_cpu_avg:.1f}% > {policy.scale_up_threshold:.0%}",
                )

        # --- Scale UP ---
        if role == "worker" and queue_depth > policy.scale_up_queue_depth and current < policy.max_replicas:
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

            _record_scaling_event(
                service=decision.service,
                action=decision.action,
                from_replicas=decision.current_replicas,
                to_replicas=decision.desired_replicas,
                reason=decision.reason,
                success=success,
            )

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
            _record_scaling_event(
                service=decision.service,
                action=decision.action,
                from_replicas=decision.current_replicas,
                to_replicas=decision.desired_replicas,
                reason=decision.reason,
                success=False,
            )
            logger.error("Failed to scale %s: %s", decision.service, e)
            return False

    async def _scale_via_cli(self, decision: ScalingDecision) -> bool:
        """Scale via Docker SDK (works with Swarm)."""
        from app.services.scaling.docker_client import scale_service

        return await scale_service(decision.service, decision.desired_replicas)

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
                logger.warning("Infra check %s failed: %s", name, e)
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
            logger.warning("PostgreSQL health check failed: %s", e)
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
            logger.warning("Redis health check failed: %s", e)
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
                    logger.debug("S3 bucket check failed for %s", bucket.get("Name", "?"), exc_info=True)
            # Storage usage is informational — alert if any bucket check fails
            # In production, actual byte-level tracking would use CloudWatch/metrics
        except Exception as e:
            logger.warning("Garage/S3 health check failed: %s", e)
        return alerts

    async def evaluate_and_execute(self, metrics: dict | ClusterMetrics) -> list[ScalingDecision]:
        """Evaluate all policies, execute scaling decisions, check infrastructure, and auto-heal.

        Accepts either a legacy flat dict or a ClusterMetrics object.  When a
        ClusterMetrics object is provided, real per-service CPU is used for
        utilization-based scaling, auto-healing runs for failed tasks, and
        system resource alerts are generated.
        """
        cluster: ClusterMetrics | None = None
        flat_metrics: dict

        if isinstance(metrics, ClusterMetrics):
            cluster = metrics
            flat_metrics = self._cluster_to_flat(cluster)
        else:
            flat_metrics = metrics

        decisions = await self.evaluate(flat_metrics, cluster=cluster)
        for decision in decisions:
            if decision.action != "none":
                await self.execute(decision)

        # --- Auto-healing ---
        heal_actions: list[str] = []
        if cluster is not None:
            auto_heal_enabled = getattr(self.settings, "AUTO_HEAL_ENABLED", True)
            if auto_heal_enabled:
                heal_actions = await self._auto_heal(cluster)

        # --- Infrastructure checks ---
        infra_alerts = await self.check_infrastructure()

        # --- System resource alerts ---
        system_alerts: list[str] = []
        if cluster is not None:
            system_alerts = self._check_system_resources(cluster)

        all_alerts = infra_alerts + system_alerts
        for alert_msg in all_alerts:
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
                logger.warning("Failed to send infra alert: %s", e)

        for action_msg in heal_actions:
            logger.info("Auto-heal action: %s", action_msg)

        return decisions

    # ------------------------------------------------------------------
    # Auto-healing
    # ------------------------------------------------------------------

    async def _auto_heal(self, metrics: ClusterMetrics) -> list[str]:
        """Detect and attempt to fix failing services. Returns list of actions taken."""
        actions: list[str] = []
        cooldown = getattr(self.settings, "AUTO_HEAL_COOLDOWN_SECS", 300)
        now = time.monotonic()

        for name, svc in metrics.services.items():
            needs_heal = False
            reason = ""

            # Priority 1: Service has 0 healthy replicas — immediate restart
            if svc.running_tasks == 0 and svc.desired_replicas > 0:
                needs_heal = True
                reason = f"0 healthy replicas (desired {svc.desired_replicas})"
            # Priority 2: Service has failed tasks
            elif svc.failed_tasks > 0 and svc.desired_replicas > 0:
                needs_heal = True
                reason = f"{svc.failed_tasks} failed tasks"

            if not needs_heal:
                continue

            # Respect per-service cooldown to avoid restart storms
            heal_key = f"_heal_{name}"
            fail_count_key = f"_heal_fail_{name}"
            last_heal = getattr(self, heal_key, 0.0)

            # Skip cooldown for 0-replica emergencies
            if svc.running_tasks > 0 and now - last_heal < cooldown:
                continue

            logger.warning(
                "Auto-heal: %s — %s, attempting restart",
                name, reason,
            )
            try:
                from app.services.scaling.docker_client import restart_service

                success = await restart_service(name)
                if success:
                    msg = f"Restarted {name} ({reason})"
                    actions.append(msg)
                    logger.info("Auto-healed %s: %s", name, reason)
                    _record_scaling_event(name, "heal_restart", svc.running_tasks, svc.desired_replicas, reason, True)
                    # Reset fail counter on success
                    object.__setattr__(self, fail_count_key, 0)
                else:
                    fail_count = getattr(self, fail_count_key, 0) + 1
                    object.__setattr__(self, fail_count_key, fail_count)
                    msg = f"Failed to restart {name}"
                    actions.append(msg)
                    logger.error("Auto-heal failed for %s (attempt %d)", name, fail_count)
                    _record_scaling_event(name, "heal_restart", svc.running_tasks, svc.desired_replicas, reason, False)

                    # After 2 consecutive failures, send urgent admin alert
                    if fail_count >= 2:
                        logger.critical(
                            "Auto-heal ALERT: %s failed %d consecutive restarts — admin intervention needed.",
                            name, fail_count,
                        )
                        try:
                            from app.services.notifications import send_notification
                            await send_notification(
                                title=f"Auto-Heal Failed: {name}",
                                message=(
                                    f"Service {name} has failed {fail_count} consecutive restart attempts. "
                                    f"Reason: {reason}."
                                ),
                                priority="urgent",
                                tags=["critical", "auto-heal", "admin"],
                            )
                        except Exception as notify_exc:
                            logger.warning("Failed to send heal alert: %s", notify_exc)
            except Exception as exc:
                fail_count = getattr(self, fail_count_key, 0) + 1
                object.__setattr__(self, fail_count_key, fail_count)
                msg = f"Auto-heal error for {name}: {exc}"
                actions.append(msg)
                logger.error("Auto-heal exception for %s (attempt %d): %s", name, fail_count, exc)
                _record_scaling_event(name, "heal_restart", svc.running_tasks, svc.desired_replicas, reason, False)

            # Record heal timestamp regardless of outcome to enforce cooldown
            object.__setattr__(self, heal_key, now)
        return actions

    # ------------------------------------------------------------------
    # System resource alerts
    # ------------------------------------------------------------------

    def _check_system_resources(self, metrics: ClusterMetrics) -> list[str]:
        """Generate alerts for system-level resource pressure."""
        alerts: list[str] = []
        sys = metrics.system

        mem_threshold = getattr(self.settings, "SYSTEM_MEMORY_ALERT_THRESHOLD", 90)
        disk_threshold = getattr(self.settings, "SYSTEM_DISK_ALERT_THRESHOLD", 85)
        load_multiplier = getattr(self.settings, "SYSTEM_LOAD_ALERT_MULTIPLIER", 2.0)

        if sys.memory_percent > mem_threshold:
            alerts.append(
                f"System memory at {sys.memory_percent:.1f}% "
                f"({sys.memory_available_mb:.0f} MB available)"
            )

        if sys.disk_percent > disk_threshold:
            alerts.append(
                f"Disk usage at {sys.disk_percent:.1f}% "
                f"({sys.disk_free_gb:.1f} GB free)"
            )

        try:
            import os

            cpu_count = os.cpu_count() or 1
        except Exception:
            cpu_count = 1
        load_threshold = cpu_count * load_multiplier
        if sys.load_avg_5m > load_threshold:
            alerts.append(
                f"Load average {sys.load_avg_5m:.2f} exceeds "
                f"{load_threshold:.1f} ({cpu_count} CPUs × {load_multiplier})"
            )

        return alerts

    # ------------------------------------------------------------------
    # ClusterMetrics → flat dict adapter
    # ------------------------------------------------------------------

    @staticmethod
    def _cluster_to_flat(cluster: ClusterMetrics) -> dict:
        """Convert ClusterMetrics to the flat dict format expected by evaluate()."""
        flat: dict = {
            "queue_depth": cluster.queue.depth,
            "in_progress": cluster.queue.in_progress,
        }

        # Map service names back to role keys
        _role_map = {
            "worker": "worker",
            "app": "api",
            "ai": "ai",
            "scheduler": "scheduler",
        }
        for svc_name, svc in cluster.services.items():
            for keyword, role in _role_map.items():
                if keyword in svc_name.lower():
                    flat[f"{role}_replicas"] = svc.replicas
                    # Use real CPU % (normalised to 0-1 range)
                    flat[f"{role}_utilization"] = min(1.0, svc.cpu_percent / 100.0)
                    break

        # Ensure worker_utilization falls back to queue-based estimate if no
        # docker stats were available
        if "worker_utilization" not in flat:
            worker_count = flat.get("worker_replicas", 1)
            in_progress = flat.get("in_progress", 0)
            flat["worker_utilization"] = min(1.0, in_progress / max(1, worker_count))

        return flat

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

        return {"policies": policies, "infrastructure": infra, "recent_actions": get_scaling_history()}
