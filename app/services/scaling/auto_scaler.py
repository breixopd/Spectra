"""Reactive auto-scaling engine.

Monitors queue depth, CPU utilization, and connection counts to automatically
adjust service replica counts via a pluggable orchestrator backend.

Infrastructure services (PostgreSQL, Redis, Garage/S3) are NOT auto-scaled
via Docker replicas — they are monitored externally and alert when thresholds
are exceeded.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.services.scaling.backends import OrchestratorBackend
from app.services.scaling.config import (
    DEFAULT_RESOURCE_REQUIREMENTS,
    AutoScalerConfig,
    ServicePolicy,
)
from app.services.scaling.metrics_collector import ClusterMetrics
from app.services.scaling.notifiers import ScalingNotifier

if TYPE_CHECKING:
    from app.services.scaling.healer import ServiceHealer

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
class ScalingDecision:
    """Outcome of evaluating a scaling policy against current metrics."""

    service: str
    action: str  # "scale_up", "scale_down", "none"
    current_replicas: int
    desired_replicas: int
    reason: str


class AutoScaler:
    """Reactive auto-scaler with pluggable backend and notifications."""

    def __init__(
        self,
        config: AutoScalerConfig,
        backend: OrchestratorBackend,
        notifier: ScalingNotifier,
    ) -> None:
        self.config = config
        self.backend = backend
        self.notifier = notifier

        # Healer for enhanced diagnostics (lazy-initialized)
        self._healer: ServiceHealer | None = None

        # Runtime state per role
        self._last_scale_action: dict[str, float] = {}
        self._queue_idle_since: dict[str, float] = {}

        # Auto-heal state per service name
        self._heal_timestamps: dict[str, float] = {}
        self._heal_fail_counts: dict[str, int] = {}

    @property
    def healer(self) -> ServiceHealer:
        """Lazy-create the ServiceHealer instance."""
        if self._healer is None:
            from app.services.scaling.healer import ServiceHealer
            self._healer = ServiceHealer(self.backend, self.notifier, self.config)
        return self._healer

    # ------------------------------------------------------------------
    # Dynamic resource-based replica limits
    # ------------------------------------------------------------------

    async def calculate_max_replicas(self, service_key: str) -> int:
        """Calculate max replicas based on cluster resources."""
        from app.services.scaling.pool_manager import get_pool_manager

        policy = self.config.policies.get(service_key)
        if not policy:
            return 1

        service_name = policy.service_name
        reqs = DEFAULT_RESOURCE_REQUIREMENTS.get(service_name)
        if not reqs:
            return policy.max_replicas

        try:
            pool = get_pool_manager()
            capacity = await pool.get_cluster_capacity()
            per_service = capacity.get("per_service_max_replicas", {})
            dynamic_max = per_service.get(service_name, policy.max_replicas)
            return min(dynamic_max, policy.max_replicas)
        except Exception:
            logger.debug(
                "Failed to calculate dynamic max replicas for %s, using policy default",
                service_key,
            )
            return policy.max_replicas

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def policies(self) -> dict[str, ServicePolicy]:
        """Access configured policies."""
        return self.config.policies

    # ------------------------------------------------------------------
    # Config operations for admin UI
    # ------------------------------------------------------------------

    def reload_config(self, config: AutoScalerConfig) -> None:
        """Replace configuration (e.g. after DB settings change)."""
        self.config = config

    def get_config_snapshot(self) -> dict:
        """Return all current scaling config values for the admin UI."""
        policies = self.config.policies
        worker = policies.get("worker")
        api = policies.get("api")
        ai = policies.get("ai")
        return {
            "scaling.worker.min_replicas": worker.min_replicas if worker else 1,
            "scaling.worker.max_replicas": worker.max_replicas if worker else 10,
            "scaling.api.min_replicas": api.min_replicas if api else 2,
            "scaling.api.max_replicas": api.max_replicas if api else 8,
            "scaling.ai.max_replicas": ai.max_replicas if ai else 4,
            "scaling.cooldown_secs": worker.cooldown_secs if worker else 300,
            "scaling.idle_secs": worker.idle_timeout_secs if worker else 600,
            "scaling.cpu_up_threshold": worker.scale_up_threshold if worker else 0.75,
            "scaling.cpu_down_threshold": worker.scale_down_threshold if worker else 0.25,
            "scaling.queue_threshold": worker.scale_up_queue_depth if worker else 5,
            "scaling.enabled": self.config.enabled,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self, metrics: dict, cluster: ClusterMetrics | None = None,
    ) -> list[ScalingDecision]:
        """Evaluate all policies and return scaling decisions."""
        decisions: list[ScalingDecision] = []
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

            if cluster_mem_max > self.config.memory_critical_percent:
                cluster_alerts.append(
                    f"EMERGENCY: Node memory at {cluster_mem_max:.1f}%"
                )
            elif cluster_mem_max > self.config.memory_warning_percent:
                cluster_alerts.append(
                    f"WARNING: Node memory at {cluster_mem_max:.1f}%"
                )

            if cluster_disk_min_gb < self.config.disk_critical_gb:
                cluster_alerts.append(
                    f"CRITICAL: Disk free {cluster_disk_min_gb:.1f}GB on a node"
                )
            elif cluster_disk_min_gb < self.config.disk_warning_gb:
                cluster_alerts.append(
                    f"WARNING: Disk free {cluster_disk_min_gb:.1f}GB on a node"
                )

        for alert in cluster_alerts:
            logger.warning("Cluster resource alert: %s", alert)

        # Calculate dynamic max replicas from cluster resources
        dynamic_max: dict[str, int] = {}
        for role in self.config.policies:
            dynamic_max[role] = await self.calculate_max_replicas(role)

        for role, policy in self.config.policies.items():
            last_action = self._last_scale_action.get(role, 0.0)
            if now - last_action < policy.cooldown_secs:
                continue

            effective_max = dynamic_max.get(role, policy.max_replicas)
            decision = self._evaluate_policy(
                role, policy, metrics, now,
                cluster_cpu_avg=cluster_cpu_avg,
                cluster_mem_max=cluster_mem_max,
                effective_max_replicas=effective_max,
            )
            if decision.action != "none":
                decisions.append(decision)

        return decisions

    def _evaluate_policy(
        self,
        role: str,
        policy: ServicePolicy,
        metrics: dict,
        now: float,
        *,
        cluster_cpu_avg: float = 0.0,
        cluster_mem_max: float = 0.0,
        effective_max_replicas: int | None = None,
    ) -> ScalingDecision:
        current = metrics.get(f"{role}_replicas", 1)
        utilization = metrics.get(f"{role}_utilization", 0.0)
        queue_depth = metrics.get("queue_depth", 0)
        queue_idle_since = self._queue_idle_since.get(role, 0.0)
        max_reps = (
            effective_max_replicas
            if effective_max_replicas is not None
            else policy.max_replicas
        )

        svc = policy.service_name

        # --- Emergency: cluster memory pressure (>95%) ---
        if (
            cluster_mem_max > self.config.memory_critical_percent
            and role == "worker"
            and current > policy.min_replicas
        ):
            return ScalingDecision(
                svc, "none", current, current,
                f"Memory emergency ({cluster_mem_max:.0f}%) \u2014 holding replicas",
            )

        # --- Cluster CPU-based scale-up ---
        if cluster_cpu_avg > 0 and role in ("worker", "api", "ai"):
            cluster_util = cluster_cpu_avg / 100.0
            if cluster_util > policy.scale_up_threshold and current < max_reps:
                return ScalingDecision(
                    svc, "scale_up", current,
                    min(current + 1, max_reps),
                    f"Cluster CPU avg {cluster_cpu_avg:.1f}% > {policy.scale_up_threshold:.0%}",
                )

        # --- Scale UP on queue depth ---
        if (
            role == "worker"
            and queue_depth > policy.scale_up_queue_depth
            and current < max_reps
        ):
            desired = min(
                current + max(1, queue_depth // policy.scale_up_queue_depth),
                max_reps,
            )
            return ScalingDecision(
                svc, "scale_up", current, desired,
                f"Queue depth {queue_depth} > threshold {policy.scale_up_queue_depth}",
            )

        # --- Scale UP on utilization ---
        if utilization > policy.scale_up_threshold and current < max_reps:
            return ScalingDecision(
                svc, "scale_up", current,
                min(current + 1, max_reps),
                f"Utilization {utilization:.0%} > {policy.scale_up_threshold:.0%}",
            )

        # --- Scale DOWN ---
        if role == "worker" and queue_depth == 0:
            if queue_idle_since == 0:
                self._queue_idle_since[role] = now
            elif (
                now - queue_idle_since > policy.idle_timeout_secs
                and current > policy.min_replicas
            ):
                return ScalingDecision(
                    svc, "scale_down", current,
                    max(current - 1, policy.min_replicas),
                    f"Queue idle for {int(now - queue_idle_since)}s",
                )
        else:
            self._queue_idle_since[role] = 0

        if utilization < policy.scale_down_threshold and current > policy.min_replicas:
            if queue_idle_since == 0:
                self._queue_idle_since[role] = now
            elif now - queue_idle_since > policy.idle_timeout_secs:
                return ScalingDecision(
                    svc, "scale_down", current,
                    max(current - 1, policy.min_replicas),
                    f"Utilization {utilization:.0%} < {policy.scale_down_threshold:.0%}",
                )

        return ScalingDecision(svc, "none", current, current, "Within thresholds")

    async def execute(self, decision: ScalingDecision) -> bool:
        """Execute a scaling decision via the orchestrator backend."""
        if decision.action == "none":
            return True

        try:
            result = await self.backend.scale(decision.service, decision.desired_replicas)
            success = result.success

            _record_scaling_event(
                service=decision.service,
                action=decision.action,
                from_replicas=decision.current_replicas,
                to_replicas=decision.desired_replicas,
                reason=decision.reason,
                success=success,
            )

            if success:
                for role, policy in self.config.policies.items():
                    if policy.service_name == decision.service:
                        self._last_scale_action[role] = time.monotonic()
                        self._queue_idle_since[role] = 0
                        break

                logger.info(
                    "Scaled %s: %d -> %d replicas (%s)",
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

    async def evaluate_and_execute(
        self,
        metrics: dict | ClusterMetrics,
        *,
        infra_alerts: list[str] | None = None,
    ) -> list[ScalingDecision]:
        """Evaluate all policies, execute scaling decisions, auto-heal, and alert."""
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
        if cluster is not None and self.config.heal_enabled:
            heal_actions = await self._auto_heal(cluster)
            # Enhanced diagnostics for services that failed basic healing
            for name, fail_count in list(self._heal_fail_counts.items()):
                if fail_count >= self.config.heal_max_retries:
                    diag = await self.healer.diagnose_and_heal(
                        name, issue="repeated_heal_failure",
                    )
                    if diag.resolved:
                        self._heal_fail_counts[name] = 0
                        heal_actions.append(
                            f"Healer resolved {name}: {diag.summary}"
                        )
                    else:
                        heal_actions.append(
                            f"Healer could not resolve {name}: {diag.summary}"
                        )

        # --- System resource alerts ---
        system_alerts: list[str] = []
        if cluster is not None:
            system_alerts = self._check_system_resources(cluster)

        all_alerts = (infra_alerts or []) + system_alerts
        for alert_msg in all_alerts:
            logger.warning("Infrastructure alert: %s", alert_msg)
            await self.notifier.notify(
                "Infrastructure Alert", alert_msg, level="warning",
            )

        for action_msg in heal_actions:
            logger.info("Auto-heal action: %s", action_msg)

        return decisions

    # ------------------------------------------------------------------
    # Auto-healing
    # ------------------------------------------------------------------

    async def _auto_heal(self, metrics: ClusterMetrics) -> list[str]:
        """Detect and attempt to fix failing services."""
        actions: list[str] = []
        now = time.monotonic()

        for name, svc in metrics.services.items():
            needs_heal = False
            reason = ""

            if svc.running_tasks == 0 and svc.desired_replicas > 0:
                needs_heal = True
                reason = f"0 healthy replicas (desired {svc.desired_replicas})"
            elif svc.failed_tasks > 0 and svc.desired_replicas > 0:
                needs_heal = True
                reason = f"{svc.failed_tasks} failed tasks"

            if not needs_heal:
                continue

            last_heal = self._heal_timestamps.get(name, 0.0)
            if svc.running_tasks > 0 and now - last_heal < self.config.heal_cooldown_secs:
                continue

            logger.warning("Auto-heal: %s \u2014 %s, attempting restart", name, reason)
            try:
                result = await self.backend.restart(name)
                if result.success:
                    msg = f"Restarted {name} ({reason})"
                    actions.append(msg)
                    logger.info("Auto-healed %s: %s", name, reason)
                    _record_scaling_event(
                        name, "heal_restart",
                        svc.running_tasks, svc.desired_replicas, reason, True,
                    )
                    self._heal_fail_counts[name] = 0
                else:
                    fail_count = self._heal_fail_counts.get(name, 0) + 1
                    self._heal_fail_counts[name] = fail_count
                    msg = f"Failed to restart {name}"
                    actions.append(msg)
                    logger.error(
                        "Auto-heal failed for %s (attempt %d)", name, fail_count,
                    )
                    _record_scaling_event(
                        name, "heal_restart",
                        svc.running_tasks, svc.desired_replicas, reason, False,
                    )

                    if fail_count >= self.config.heal_max_retries:
                        logger.critical(
                            "Auto-heal ALERT: %s failed %d consecutive restarts",
                            name, fail_count,
                        )
                        await self.notifier.notify(
                            f"Auto-Heal Failed: {name}",
                            (
                                f"Service {name} has failed {fail_count} "
                                f"consecutive restart attempts. Reason: {reason}."
                            ),
                            level="critical",
                        )
            except Exception as exc:
                fail_count = self._heal_fail_counts.get(name, 0) + 1
                self._heal_fail_counts[name] = fail_count
                msg = f"Auto-heal error for {name}: {exc}"
                actions.append(msg)
                logger.error(
                    "Auto-heal exception for %s (attempt %d): %s",
                    name, fail_count, exc,
                )
                _record_scaling_event(
                    name, "heal_restart",
                    svc.running_tasks, svc.desired_replicas, reason, False,
                )

            self._heal_timestamps[name] = now
        return actions

    # ------------------------------------------------------------------
    # System resource alerts
    # ------------------------------------------------------------------

    def _check_system_resources(self, metrics: ClusterMetrics) -> list[str]:
        """Generate alerts for system-level resource pressure."""
        alerts: list[str] = []
        sys = metrics.system

        if sys.memory_percent > self.config.system_memory_alert_threshold:
            alerts.append(
                f"System memory at {sys.memory_percent:.1f}% "
                f"({sys.memory_available_mb:.0f} MB available)"
            )

        if sys.disk_percent > self.config.system_disk_alert_threshold:
            alerts.append(
                f"Disk usage at {sys.disk_percent:.1f}% "
                f"({sys.disk_free_gb:.1f} GB free)"
            )

        cpu_count = os.cpu_count() or 1
        load_threshold = cpu_count * self.config.system_load_alert_multiplier
        if sys.load_avg_5m > load_threshold:
            alerts.append(
                f"Load average {sys.load_avg_5m:.2f} exceeds "
                f"{load_threshold:.1f} ({cpu_count} CPUs x "
                f"{self.config.system_load_alert_multiplier})"
            )

        return alerts

    # ------------------------------------------------------------------
    # ClusterMetrics -> flat dict adapter
    # ------------------------------------------------------------------

    @staticmethod
    def _cluster_to_flat(cluster: ClusterMetrics) -> dict:
        """Convert ClusterMetrics to the flat dict format expected by evaluate()."""
        flat: dict = {
            "queue_depth": cluster.queue.depth,
            "in_progress": cluster.queue.in_progress,
        }

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
                    flat[f"{role}_utilization"] = min(1.0, svc.cpu_percent / 100.0)
                    break

        if "worker_utilization" not in flat:
            worker_count = flat.get("worker_replicas", 1)
            in_progress = flat.get("in_progress", 0)
            flat["worker_utilization"] = min(1.0, in_progress / max(1, worker_count))

        return flat

    def get_status(self) -> dict:
        """Return current auto-scaler status and policy state."""
        now = time.monotonic()
        policies = {}
        for role, policy in self.config.policies.items():
            last_action = self._last_scale_action.get(role, 0.0)
            idle_since = self._queue_idle_since.get(role, 0.0)
            cooldown_remaining = max(0, policy.cooldown_secs - (now - last_action))
            policies[role] = {
                "service_name": policy.service_name,
                "min_replicas": policy.min_replicas,
                "max_replicas": policy.max_replicas,
                "scale_up_threshold": policy.scale_up_threshold,
                "scale_down_threshold": policy.scale_down_threshold,
                "scale_up_queue_depth": policy.scale_up_queue_depth,
                "cooldown_secs": policy.cooldown_secs,
                "cooldown_remaining_secs": round(cooldown_remaining, 1),
                "idle_since_secs": round(now - idle_since, 1) if idle_since else 0,
            }

        return {"policies": policies, "recent_actions": get_scaling_history()}
