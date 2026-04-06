"""Reactive auto-scaling engine.

Monitors queue depth, CPU utilization, and connection counts to automatically
adjust service replica counts via Docker API or CLI.
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
class ScalingDecision:
    """Outcome of evaluating a scaling policy against current metrics."""

    service: str
    action: str  # "scale_up", "scale_down", "none"
    current_replicas: int
    desired_replicas: int
    reason: str


class AutoScaler:
    """Reactive auto-scaler that adjusts Docker service replica counts."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.policies: dict[str, ScalingPolicy] = {}
        self._init_policies()

    def _init_policies(self) -> None:
        """Initialize default policies per service from settings."""
        cooldown = getattr(self.settings, "AUTOSCALE_COOLDOWN_SECS", 300)
        idle_secs = getattr(self.settings, "AUTOSCALE_IDLE_SECS", 300)

        self.policies = {
            "worker": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_WORKER_SERVICE", "spectra_worker"),
                min_replicas=getattr(self.settings, "AUTOSCALE_WORKER_MIN", 1),
                max_replicas=getattr(self.settings, "AUTOSCALE_WORKER_MAX", 10),
                scale_up_queue_depth=getattr(self.settings, "AUTOSCALE_QUEUE_THRESHOLD", 10),
                cooldown_secs=cooldown,
                scale_down_queue_idle_secs=idle_secs,
            ),
            "api": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_API_SERVICE", "spectra_app"),
                min_replicas=getattr(self.settings, "AUTOSCALE_API_MIN", 1),
                max_replicas=getattr(self.settings, "AUTOSCALE_API_MAX", 5),
                scale_up_threshold=0.85,
                cooldown_secs=cooldown,
                scale_down_queue_idle_secs=idle_secs,
            ),
            "ai": ScalingPolicy(
                service_name=getattr(self.settings, "SWARM_AI_SERVICE", "spectra_ai-svc"),
                min_replicas=1,
                max_replicas=getattr(self.settings, "AUTOSCALE_AI_MAX", 3),
                cooldown_secs=cooldown,
                scale_down_queue_idle_secs=idle_secs,
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
        return {"policies": policies}
