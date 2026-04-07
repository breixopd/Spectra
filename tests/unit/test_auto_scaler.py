"""Unit tests for reactive auto-scaling engine."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.scaling.auto_scaler import (
    AutoScaler,
    InfraMonitorConfig,
    ScalingDecision,
    ScalingPolicy,
)


@pytest.fixture
def settings():
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
    mock.INFRA_MONITOR_ENABLED = True
    mock.INFRA_MONITOR_PG_THRESHOLD = 80
    mock.INFRA_MONITOR_REDIS_THRESHOLD = 85
    mock.INFRA_MONITOR_STORAGE_THRESHOLD = 90
    return mock


@pytest.fixture
def scaler(settings):
    return AutoScaler(settings)


class TestScalingPolicy:
    def test_default_values(self):
        p = ScalingPolicy(service_name="test")
        assert p.min_replicas == 1
        assert p.max_replicas == 10
        assert p.cooldown_secs == 300


class TestInfraMonitorConfig:
    def test_default_values(self):
        c = InfraMonitorConfig(service_name="postgres")
        assert c.enabled is True
        assert c.alert_threshold_pct == 85.0

    def test_custom_threshold(self):
        c = InfraMonitorConfig("redis", alert_threshold_pct=90.0)
        assert c.alert_threshold_pct == 90.0


class TestAutoScaler:
    def test_has_all_service_policies(self, scaler):
        assert "worker" in scaler.policies
        assert "api" in scaler.policies
        assert "ai" in scaler.policies
        assert "scheduler" in scaler.policies

    def test_has_infra_monitors(self, scaler):
        assert "postgres" in scaler.infra_monitors
        assert "redis" in scaler.infra_monitors
        assert "garage" in scaler.infra_monitors

    def test_scheduler_policy_limits(self, scaler):
        sched = scaler.policies["scheduler"]
        assert sched.min_replicas == 1
        assert sched.max_replicas == 2

    @pytest.mark.asyncio
    async def test_no_decisions_when_within_thresholds(self, scaler):
        metrics = {"queue_depth": 2, "worker_replicas": 2, "worker_utilization": 0.5}
        decisions = await scaler.evaluate(metrics)
        assert all(d.action == "none" for d in decisions)

    @pytest.mark.asyncio
    async def test_scale_up_on_high_queue_depth(self, scaler):
        metrics = {"queue_depth": 20, "worker_replicas": 1, "worker_utilization": 0.5}
        decisions = await scaler.evaluate(metrics)
        worker_decisions = [d for d in decisions if "worker" in d.service]
        assert any(d.action == "scale_up" for d in worker_decisions)

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
            for p in scaler.policies.values():
                if p.service_name == d.service:
                    p.last_scale_action = time.monotonic()
        # Second evaluation should NOT trigger (in cooldown)
        decisions2 = await scaler.evaluate(metrics)
        worker_decisions2 = [d for d in decisions2 if "worker" in d.service and d.action == "scale_up"]
        assert len(worker_decisions2) == 0

    @pytest.mark.asyncio
    async def test_scale_down_on_idle(self, scaler):
        scaler.policies["worker"].queue_idle_since = time.monotonic() - 700
        metrics = {"queue_depth": 0, "worker_replicas": 3, "worker_utilization": 0.1}
        decisions = await scaler.evaluate(metrics)
        worker_decisions = [d for d in decisions if "worker" in d.service]
        assert any(d.action == "scale_down" for d in worker_decisions)

    @pytest.mark.asyncio
    async def test_no_scale_down_below_min(self, scaler):
        scaler.policies["worker"].queue_idle_since = time.monotonic() - 700
        metrics = {"queue_depth": 0, "worker_replicas": 1, "worker_utilization": 0.0}
        decisions = await scaler.evaluate(metrics)
        for d in decisions:
            if "worker" in d.service:
                assert d.desired_replicas >= 1

    @pytest.mark.asyncio
    async def test_execute_scale_via_cli(self, scaler):
        decision = ScalingDecision("spectra_worker", "scale_up", 1, 2, "test")
        with patch("asyncio.to_thread") as mock_thread:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_thread.return_value = mock_result
            success = await scaler.execute(decision)
            assert success

    def test_get_status_includes_infra(self, scaler):
        status = scaler.get_status()
        assert "policies" in status
        assert "infrastructure" in status
        assert "postgres" in status["infrastructure"]
        assert "scheduler" in status["policies"]

    @pytest.mark.asyncio
    async def test_check_infrastructure_returns_list(self, scaler):
        # Disable infra monitors so no real connections are attempted
        for m in scaler.infra_monitors.values():
            m.enabled = False
        alerts = await scaler.check_infrastructure()
        assert isinstance(alerts, list)
        assert len(alerts) == 0
