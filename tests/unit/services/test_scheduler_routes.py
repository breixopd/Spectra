"""Tests for scheduler FastAPI route handlers (direct invocation; avoids app lifespan).

The production ``spectra_scheduler.routes.app`` attaches a lifespan that starts
leader election against Postgres; hitting it via ``AsyncClient`` without lifespan
controls would block CI. Calling registered handlers matches patterns in
``test_scheduler_service.py`` and still exercises route bodies with mocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import Response

import spectra_scheduler.routes as scheduler_routes
import spectra_scheduler.state as scheduler_state


def _sandbox_info(mission_id: str):
    from spectra_tools.sandbox.models import SandboxInfo

    return SandboxInfo(
        container_id="sandbox-1",
        container_name="spectra-sandbox-1",
        mission_id=mission_id,
        queue_name="mission_12345678",
        status="running",
        image="spectra-tools",
        created_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def reset_scheduler_singleton():
    prev = scheduler_state._scheduler_instance
    scheduler_state._scheduler_instance = None
    yield
    scheduler_state._scheduler_instance = prev


@pytest.mark.asyncio
async def test_healthz_returns_alive():
    body = await scheduler_routes.healthz()
    assert body == {"status": "alive", "service": "scheduler"}


@pytest.mark.asyncio
async def test_health_returns_starting_when_scheduler_not_started():
    response = Response()
    body = await scheduler_routes.health(response)
    assert response.status_code == 200
    assert body == {"status": "starting", "service": "scheduler"}


@pytest.mark.asyncio
async def test_create_sandbox_is_scheduler_owned_and_returns_safe_payload(monkeypatch):
    mission_id = str(uuid4())
    user_id = str(uuid4())
    pool = SimpleNamespace(available=True, create=AsyncMock(return_value=_sandbox_info(mission_id)))
    monkeypatch.setattr(scheduler_routes, "get_sandbox_pool", lambda: pool)

    result = await scheduler_routes.create_sandbox(
        scheduler_routes.SandboxCreateRequest(mission_id=mission_id, resource_tier="light", user_id=user_id),
    )

    assert result["container_name"] == "spectra-sandbox-1"
    assert result["queue_name"] == "mission_12345678"
    pool.create.assert_awaited_once_with(mission_id, resource_tier="light", user_id=user_id, vpn_config_path=None)


@pytest.mark.asyncio
async def test_create_sandbox_rejects_unavailable_controller(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(scheduler_routes, "get_sandbox_pool", lambda: None)
    with pytest.raises(HTTPException, match="Sandbox controller unavailable"):
        await scheduler_routes.create_sandbox(scheduler_routes.SandboxCreateRequest(mission_id=str(uuid4())))


def test_task_health_details_reports_recovering_scheduler_loop():
    scheduler_state._scheduler_instance = SimpleNamespace(
        _named_tasks={task_name: SimpleNamespace(done=lambda: False) for task_name, _ in scheduler_routes._SCHEDULER_TASK_SPECS},
        _task_restarts={"quota_reset": 1},
        _task_last_failure={"quota_reset": "RuntimeError: cache unavailable"},
    )

    details, degraded = scheduler_routes.task_health_details(scheduler_state._scheduler_instance)

    assert degraded is True
    quota = details["quota_reset"]
    assert quota["state"] == "recovering"
    assert quota["restart_count"] == 1
    assert quota["last_failure"] == "RuntimeError: cache unavailable"


@pytest.mark.asyncio
async def test_health_returns_instance_payload_when_scheduler_running():
    scheduler_state._scheduler_instance = SimpleNamespace(
        running=True,
        health=lambda: {"status": "healthy", "tasks": {"quota_reset": "alive"}, "running": True},
    )
    response = Response()
    body = await scheduler_routes.health(response)
    assert response.status_code == 200
    assert body["service"] == "scheduler"
    assert body["status"] == "healthy"
    assert body["running"] is True


@pytest.mark.asyncio
async def test_health_returns_503_when_scheduler_degraded():
    scheduler_state._scheduler_instance = SimpleNamespace(
        running=True,
        health=lambda: {"status": "degraded", "tasks": {}, "running": True},
    )
    response = Response()
    body = await scheduler_routes.health(response)
    assert response.status_code == 503
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_internal_scaling_metrics_returns_payload():
    payload = {
        "timestamp": "2026-05-01T12:00:00+00:00",
        "services": {"spectra_app": {"replicas": 1}},
        "system": {"cpu_percent": 10.0},
        "queue": {"depth": 0},
        "nodes": {"total": 1, "healthy": 1, "unhealthy": 0},
    }
    with patch.object(scheduler_routes, "_scaling_metrics_payload", AsyncMock(return_value=payload)):
        body = await scheduler_routes.internal_scaling_metrics()
    assert body == payload


@pytest.mark.asyncio
async def test_internal_scaling_action_rejects_invalid_action():
    body = await scheduler_routes.internal_scaling_action({"action": "pause", "service": "spectra_app"})
    assert body["success"] is False
    assert "Invalid action" in body.get("error", "")


@pytest.mark.asyncio
async def test_internal_scaling_action_rejects_disallowed_service():
    body = await scheduler_routes.internal_scaling_action({"action": "scale_up", "service": "unknown_svc"})
    assert body["success"] is False
    assert "not allowed" in body.get("error", "").lower()


@pytest.mark.asyncio
async def test_internal_scaling_action_scale_up_invokes_scale_service():
    fake_svc = SimpleNamespace(desired_replicas=2)
    with (
        patch(
            "spectra_scaling.docker_client.get_service",
            AsyncMock(return_value=fake_svc),
        ),
        patch(
            "spectra_scaling.docker_client.scale_service",
            AsyncMock(return_value=True),
        ) as scale_mock,
    ):
        body = await scheduler_routes.internal_scaling_action(
            {"action": "scale_up", "service": "spectra_app"},
        )
    assert body["success"] is True
    scale_mock.assert_awaited_once_with("spectra_app", 3)


@pytest.mark.asyncio
async def test_internal_updates_apply_unknown_service():
    body = await scheduler_routes.internal_update_apply({"service": "not-a-managed-service"})
    assert body["success"] is False
    assert "Unknown service" in body.get("error", "")


@pytest.mark.asyncio
async def test_internal_update_status_returns_cached_payload():
    stub = {"services": [], "checked_at": "2026-05-01T00:00:00"}
    with patch("spectra_scaling.image_updater.get_update_status", return_value=stub):
        body = await scheduler_routes.internal_update_status()
    assert body == stub


@pytest.mark.asyncio
async def test_internal_rollback_candidates_returns_wrapper():
    candidates = [{"service": "spectra_app", "previous": "sha256:abc"}]
    with patch(
        "spectra_scaling.image_updater.get_rollback_candidates",
        return_value=candidates,
    ):
        body = await scheduler_routes.internal_rollback_candidates()
    assert body == {"candidates": candidates}


@pytest.mark.asyncio
async def test_internal_rollback_rejects_missing_service():
    body = await scheduler_routes.internal_rollback({})
    assert body == {"success": False, "error": "Missing 'service' field"}


@pytest.mark.asyncio
async def test_internal_rollback_rejects_unknown_service():
    body = await scheduler_routes.internal_rollback({"service": "not-managed"})
    assert body["success"] is False
    assert "Unknown service" in body.get("error", "")
