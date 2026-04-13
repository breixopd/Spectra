"""Unit tests for reactive auto-scaling engine."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.scaling.auto_scaler import AutoScaler, ScalingDecision
from app.services.scaling.backends import OrchestratorBackend, ScaleResult
from app.services.scaling.config import AutoScalerConfig, ServicePolicy
from app.services.scaling.notifiers import ScalingNotifier


# --- Test doubles ---


class _StubBackend(OrchestratorBackend):
    """In-memory backend for tests."""

    async def scale(self, service, replicas):
        return ScaleResult(True, service, "scale", 0, replicas)

    async def restart(self, service):
        return ScaleResult(True, service, "restart")

    async def get_service_replicas(self, service):
        return 1

    async def get_service_cpu(self, service):
        return 0.0

    async def update_image(self, service, image):
        return ScaleResult(True, service, "update_image")


class _StubNotifier(ScalingNotifier):
    async def notify(self, title, message, level="info"):
        pass


# --- Helpers ---


def _default_config(**overrides):
    """Build an AutoScalerConfig with standard test policies."""
    policies = {
        "worker": ServicePolicy(
            service_name="spectra_worker",
            min_replicas=1,
            max_replicas=10,
            scale_up_threshold=0.75,
            scale_down_threshold=0.25,
            scale_up_queue_depth=5,
            cooldown_secs=300,
            idle_timeout_secs=600,
        ),
        "api": ServicePolicy(
            service_name="spectra_app",
            min_replicas=2,
            max_replicas=8,
            scale_up_threshold=0.75,
            scale_down_threshold=0.25,
            scale_up_queue_depth=0,
            cooldown_secs=120,
            idle_timeout_secs=300,
        ),
        "ai": ServicePolicy(
            service_name="spectra_ai-svc",
            min_replicas=1,
            max_replicas=4,
            scale_up_threshold=0.80,
            scale_down_threshold=0.20,
            scale_up_queue_depth=3,
            cooldown_secs=300,
            idle_timeout_secs=900,
        ),
        "scheduler": ServicePolicy(
            service_name="spectra_scheduler",
            min_replicas=1,
            max_replicas=2,
            scale_up_threshold=0,
            scale_down_threshold=0,
            scale_up_queue_depth=0,
            cooldown_secs=600,
            idle_timeout_secs=0,
        ),
    }
    return AutoScalerConfig(enabled=True, policies=policies, **overrides)


# --- Fixtures ---


@pytest.fixture
def config():
    return _default_config()


@pytest.fixture
def backend():
    return _StubBackend()


@pytest.fixture
def notifier():
    return _StubNotifier()


@pytest.fixture
def scaler(config, backend, notifier, monkeypatch):
    scaler = AutoScaler(config, backend, notifier)

    async def _policy_max(role):
        return scaler.policies[role].max_replicas

    monkeypatch.setattr(scaler, "calculate_max_replicas", AsyncMock(side_effect=_policy_max))
    return scaler


# --- Tests ---


class TestServicePolicy:
    def test_default_values(self):
        p = ServicePolicy(service_name="test")
        assert p.min_replicas == 1
        assert p.max_replicas == 10
        assert p.cooldown_secs == 300


class TestAutoScaler:
    def test_has_all_service_policies(self, scaler):
        assert "worker" in scaler.policies
        assert "api" in scaler.policies
        assert "ai" in scaler.policies
        assert "scheduler" in scaler.policies

    def test_scheduler_policy_limits(self, scaler):
        sched = scaler.policies["scheduler"]
        assert sched.min_replicas == 1
        assert sched.max_replicas == 2

    @pytest.mark.asyncio
    async def test_no_decisions_when_within_thresholds(self, scaler):
        metrics = {"queue_depth": 2, "worker_replicas": 2, "worker_utilization": 0.5}
        decisions = await scaler.evaluate(metrics)
        assert all(d.action == "none" for d in decisions)

    def test_scale_up_on_high_queue_depth(self, scaler):
        policy = scaler.policies["worker"]
        metrics = {"queue_depth": 20, "worker_replicas": 1, "worker_utilization": 0.5}

        decision = scaler._evaluate_policy(
            "worker",
            policy,
            metrics,
            now=1000.0,
            effective_max_replicas=policy.max_replicas,
        )

        assert decision.action == "scale_up"
        assert decision.service == policy.service_name
        assert decision.current_replicas == 1
        assert decision.desired_replicas == 5

    @pytest.mark.asyncio
    async def test_scale_up_respects_max(self, scaler):
        metrics = {"queue_depth": 100, "worker_replicas": 10, "worker_utilization": 0.9}
        decisions = await scaler.evaluate(metrics)
        for d in decisions:
            assert d.desired_replicas <= 10

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_scaling(self, scaler):
        metrics = {"queue_depth": 20, "worker_replicas": 1, "worker_utilization": 0.5}
        decisions = await scaler.evaluate(metrics)
        worker_decisions = [d for d in decisions if "worker" in d.service and d.action == "scale_up"]
        # Simulate execution (sets cooldown)
        for d in worker_decisions:
            for role, p in scaler.config.policies.items():
                if p.service_name == d.service:
                    scaler._last_scale_action[role] = time.monotonic()
        # Second evaluation should NOT trigger (in cooldown)
        decisions2 = await scaler.evaluate(metrics)
        worker_decisions2 = [d for d in decisions2 if "worker" in d.service and d.action == "scale_up"]
        assert len(worker_decisions2) == 0

    def test_scale_down_on_idle(self, scaler):
        policy = scaler.policies["worker"]
        now = 1000.0
        scaler._queue_idle_since["worker"] = now - policy.idle_timeout_secs - 100
        metrics = {"queue_depth": 0, "worker_replicas": 3, "worker_utilization": 0.1}

        decision = scaler._evaluate_policy(
            "worker",
            policy,
            metrics,
            now=now,
            effective_max_replicas=policy.max_replicas,
        )

        assert decision.action == "scale_down"
        assert decision.service == policy.service_name
        assert decision.current_replicas == 3
        assert decision.desired_replicas == 2

    @pytest.mark.asyncio
    async def test_no_scale_down_below_min(self, scaler):
        scaler._queue_idle_since["worker"] = time.monotonic() - 700
        metrics = {"queue_depth": 0, "worker_replicas": 1, "worker_utilization": 0.0}
        decisions = await scaler.evaluate(metrics)
        for d in decisions:
            if "worker" in d.service:
                assert d.desired_replicas >= 1

    @pytest.mark.asyncio
    async def test_execute_via_backend(self, scaler):
        decision = ScalingDecision("spectra_worker", "scale_up", 1, 2, "test")
        success = await scaler.execute(decision)
        assert success

    def test_get_status_structure(self, scaler):
        status = scaler.get_status()
        assert "policies" in status
        assert "recent_actions" in status
        assert "scheduler" in status["policies"]


class TestFromSettings:
    """AutoScalerConfig.from_settings builds config from a settings object."""

    @pytest.fixture
    def settings(self):
        mock = MagicMock()
        mock.AUTOSCALE_WORKER_MIN = 1
        mock.AUTOSCALE_WORKER_MAX = 10
        mock.AUTOSCALE_API_MIN = 2
        mock.AUTOSCALE_API_MAX = 8
        mock.AUTOSCALE_AI_MAX = 4
        mock.AUTOSCALE_QUEUE_THRESHOLD = 5
        mock.AUTOSCALE_COOLDOWN_SECS = 300
        mock.AUTOSCALE_IDLE_SECS = 300
        mock.AUTOSCALE_CPU_UP_THRESHOLD = 75
        mock.AUTOSCALE_CPU_DOWN_THRESHOLD = 25
        mock.SWARM_WORKER_SERVICE = "spectra_worker"
        mock.SWARM_API_SERVICE = "spectra_app"
        mock.SWARM_AI_SERVICE = "spectra_ai-svc"
        mock.SWARM_SCHEDULER_SERVICE = "spectra_scheduler"
        mock.AUTOSCALE_ENABLED = True
        mock.AUTO_HEAL_ENABLED = True
        mock.AUTO_HEAL_COOLDOWN_SECS = 300
        mock.SYSTEM_MEMORY_ALERT_THRESHOLD = 90
        mock.SYSTEM_DISK_ALERT_THRESHOLD = 85
        mock.SYSTEM_LOAD_ALERT_MULTIPLIER = 2.0
        return mock

    @pytest.fixture
    def db_config(self):
        return {
            "scaling.worker.min_replicas": "2",
            "scaling.worker.max_replicas": "6",
            "scaling.api.min_replicas": "1",
            "scaling.api.max_replicas": "4",
            "scaling.ai.max_replicas": "3",
            "scaling.cooldown_secs": "120",
            "scaling.idle_secs": "180",
            "scaling.cpu_up_threshold": "80",
            "scaling.cpu_down_threshold": "30",
            "scaling.queue_threshold": "8",
            "scaling.enabled": "true",
        }

    def test_from_settings_creates_all_policies(self, settings):
        config = AutoScalerConfig.from_settings(settings)
        assert config.enabled is True
        assert "worker" in config.policies
        assert "api" in config.policies
        assert "ai" in config.policies
        assert "scheduler" in config.policies

    def test_db_config_overrides_env_vars(self, settings, db_config):
        config = AutoScalerConfig.from_settings(settings, db_config=db_config)
        assert config.policies["worker"].min_replicas == 2
        assert config.policies["worker"].max_replicas == 6
        assert config.policies["api"].min_replicas == 1
        assert config.policies["api"].max_replicas == 4
        assert config.policies["ai"].max_replicas == 3
        assert config.policies["worker"].scale_up_queue_depth == 8

    def test_partial_db_config_falls_back_to_env(self, settings):
        partial = {"scaling.worker.min_replicas": "3"}
        config = AutoScalerConfig.from_settings(settings, db_config=partial)
        # DB override applied
        assert config.policies["worker"].min_replicas == 3
        # Env var still used for max
        assert config.policies["worker"].max_replicas == 10

    def test_invalid_db_value_falls_back_to_env(self, settings):
        bad = {"scaling.worker.min_replicas": "not_a_number"}
        config = AutoScalerConfig.from_settings(settings, db_config=bad)
        # Falls back to env var value
        assert config.policies["worker"].min_replicas == 1


class TestReloadConfig:
    def test_reload_changes_policies(self, backend, notifier):
        config = _default_config()
        scaler = AutoScaler(config, backend, notifier)
        assert scaler.policies["worker"].max_replicas == 10

        new_config = _default_config()
        new_config.policies["worker"] = ServicePolicy(
            service_name="spectra_worker",
            max_replicas=5,
        )
        scaler.reload_config(new_config)
        assert scaler.policies["worker"].max_replicas == 5


class TestGetConfigSnapshot:
    def test_snapshot_keys(self, scaler):
        snap = scaler.get_config_snapshot()
        expected_keys = {
            "scaling.worker.min_replicas",
            "scaling.worker.max_replicas",
            "scaling.api.min_replicas",
            "scaling.api.max_replicas",
            "scaling.ai.max_replicas",
            "scaling.cooldown_secs",
            "scaling.idle_secs",
            "scaling.cpu_up_threshold",
            "scaling.cpu_down_threshold",
            "scaling.queue_threshold",
            "scaling.enabled",
        }
        assert set(snap.keys()) == expected_keys

    def test_snapshot_reflects_config(self, backend, notifier):
        config = _default_config()
        config.policies["worker"] = ServicePolicy(
            service_name="spectra_worker",
            max_replicas=6,
        )
        scaler = AutoScaler(config, backend, notifier)
        snap = scaler.get_config_snapshot()
        assert snap["scaling.worker.max_replicas"] == 6
        assert snap["scaling.enabled"] is True
