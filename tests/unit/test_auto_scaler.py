"""Unit tests for reactive auto-scaling engine."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.scaling.auto_scaler import AutoScaler, ScalingDecision, ScalingPolicy


@pytest.fixture
def settings():
    mock = MagicMock()
    mock.AUTOSCALE_WORKER_MIN = 1
    mock.AUTOSCALE_WORKER_MAX = 5
    mock.AUTOSCALE_API_MIN = 1
    mock.AUTOSCALE_API_MAX = 3
    mock.AUTOSCALE_AI_MAX = 2
    mock.AUTOSCALE_QUEUE_THRESHOLD = 10
    mock.AUTOSCALE_COOLDOWN_SECS = 300
    mock.AUTOSCALE_IDLE_SECS = 300
    mock.SWARM_WORKER_SERVICE = "spectra_worker"
    mock.SWARM_API_SERVICE = "spectra_app"
    mock.SWARM_AI_SERVICE = "spectra_ai-svc"
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


class TestAutoScaler:
    @pytest.mark.asyncio
    async def test_no_decisions_when_within_thresholds(self, scaler):
        metrics = {"queue_depth": 5, "worker_replicas": 2, "worker_utilization": 0.5}
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
        metrics = {"queue_depth": 100, "worker_replicas": 5, "worker_utilization": 0.9}
        decisions = await scaler.evaluate(metrics)
        for d in decisions:
            assert d.desired_replicas <= 5

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
        scaler.policies["worker"].queue_idle_since = time.monotonic() - 400
        metrics = {"queue_depth": 0, "worker_replicas": 3, "worker_utilization": 0.1}
        decisions = await scaler.evaluate(metrics)
        worker_decisions = [d for d in decisions if "worker" in d.service]
        assert any(d.action == "scale_down" for d in worker_decisions)

    @pytest.mark.asyncio
    async def test_no_scale_down_below_min(self, scaler):
        scaler.policies["worker"].queue_idle_since = time.monotonic() - 400
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
