"""Autoscaler configuration — standalone, no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field


def _as_bool(value) -> bool:
    """Coerce a string/bool/int to bool for config values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ServicePolicy:
    """Scaling policy for a single service."""

    service_name: str
    min_replicas: int = 1
    max_replicas: int = 10
    scale_up_threshold: float = 0.75  # CPU/queue utilization
    scale_down_threshold: float = 0.25
    scale_up_queue_depth: int = 10  # queue depth trigger
    cooldown_secs: int = 300
    idle_timeout_secs: int = 600


@dataclass
class AutoScalerConfig:
    """Complete autoscaler configuration."""

    enabled: bool = False
    policies: dict[str, ServicePolicy] = field(default_factory=dict)
    check_interval_secs: int = 60

    # Resource thresholds
    memory_warning_percent: float = 85.0
    memory_critical_percent: float = 95.0
    disk_warning_gb: float = 10.0
    disk_critical_gb: float = 5.0
    cpu_warning_percent: float = 90.0

    # Auto-healing
    heal_enabled: bool = True
    heal_max_retries: int = 2
    heal_cooldown_secs: int = 300

    # System alerts
    system_memory_alert_threshold: float = 90.0
    system_disk_alert_threshold: float = 85.0
    system_load_alert_multiplier: float = 2.0

    @classmethod
    def from_settings(cls, settings, db_config: dict | None = None) -> AutoScalerConfig:
        """Create config from a Spectra Settings object (integration bridge).

        Resolution order per value: db_config → settings attribute → hard-coded default.
        """
        db = db_config or {}

        def _cfg(db_key: str, env_attr: str, default, cast_fn=int):
            if db_key in db:
                try:
                    return cast_fn(db[db_key])
                except (ValueError, TypeError):
                    pass
            val = getattr(settings, env_attr, None)
            if val is not None:
                try:
                    return cast_fn(val)
                except (ValueError, TypeError):
                    pass
            return default

        cooldown = _cfg("scaling.cooldown_secs", "AUTOSCALE_COOLDOWN_SECS", 300)
        idle_secs = _cfg("scaling.idle_secs", "AUTOSCALE_IDLE_SECS", 300)
        cpu_up = _cfg("scaling.cpu_up_threshold", "AUTOSCALE_CPU_UP_THRESHOLD", 75) / 100.0
        cpu_down = _cfg("scaling.cpu_down_threshold", "AUTOSCALE_CPU_DOWN_THRESHOLD", 25) / 100.0
        queue_threshold = _cfg("scaling.queue_threshold", "AUTOSCALE_QUEUE_THRESHOLD", 5)

        policies = {
            "worker": ServicePolicy(
                service_name=getattr(settings, "SWARM_WORKER_SERVICE", "spectra_worker"),
                min_replicas=_cfg("scaling.worker.min_replicas", "AUTOSCALE_WORKER_MIN", 1),
                max_replicas=_cfg("scaling.worker.max_replicas", "AUTOSCALE_WORKER_MAX", 10),
                scale_up_threshold=cpu_up,
                scale_down_threshold=cpu_down,
                scale_up_queue_depth=queue_threshold,
                cooldown_secs=cooldown,
                idle_timeout_secs=max(idle_secs, 600),
            ),
            "api": ServicePolicy(
                service_name=getattr(settings, "SWARM_API_SERVICE", "spectra_app"),
                min_replicas=_cfg("scaling.api.min_replicas", "AUTOSCALE_API_MIN", 2),
                max_replicas=_cfg("scaling.api.max_replicas", "AUTOSCALE_API_MAX", 8),
                scale_up_threshold=cpu_up,
                scale_down_threshold=cpu_down,
                scale_up_queue_depth=0,
                cooldown_secs=min(cooldown, 120),
                idle_timeout_secs=min(idle_secs, 300),
            ),
            "ai": ServicePolicy(
                service_name=getattr(settings, "SWARM_AI_SERVICE", "spectra_ai-svc"),
                min_replicas=1,
                max_replicas=_cfg("scaling.ai.max_replicas", "AUTOSCALE_AI_MAX", 4),
                scale_up_threshold=0.80,
                scale_down_threshold=0.20,
                scale_up_queue_depth=3,
                cooldown_secs=cooldown,
                idle_timeout_secs=max(idle_secs, 900),
            ),
            "scheduler": ServicePolicy(
                service_name=getattr(settings, "SWARM_SCHEDULER_SERVICE", "spectra_scheduler"),
                min_replicas=1,
                max_replicas=2,
                scale_up_threshold=0,
                scale_down_threshold=0,
                scale_up_queue_depth=0,
                cooldown_secs=600,
                idle_timeout_secs=0,
            ),
        }

        return cls(
            enabled=_cfg("scaling.enabled", "AUTOSCALE_ENABLED", True, cast_fn=_as_bool),
            policies=policies,
            heal_enabled=_as_bool(getattr(settings, "AUTO_HEAL_ENABLED", True)),
            heal_cooldown_secs=int(getattr(settings, "AUTO_HEAL_COOLDOWN_SECS", 300)),
            system_memory_alert_threshold=float(
                getattr(settings, "SYSTEM_MEMORY_ALERT_THRESHOLD", 90)
            ),
            system_disk_alert_threshold=float(
                getattr(settings, "SYSTEM_DISK_ALERT_THRESHOLD", 85)
            ),
            system_load_alert_multiplier=float(
                getattr(settings, "SYSTEM_LOAD_ALERT_MULTIPLIER", 2.0)
            ),
        )
