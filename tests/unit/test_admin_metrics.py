"""Unit tests for admin metrics, cost-summary, and usage-stats endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.admin.metrics import router as metrics_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin() -> MagicMock:
    u = MagicMock()
    u.id = "uid-admin"
    u.username = "admin"
    u.email = "admin@test.com"
    u.role = "admin"
    u.is_active = True
    u.is_superuser = True
    u.plan_id = None
    u.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    u.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    return u


def _build_app(override_user: MagicMock | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_router)

    if override_user is not None:
        from app.api.dependencies import get_current_active_user

        app.dependency_overrides[get_current_active_user] = lambda: override_user
    return app


def _mock_session() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# /api/admin/metrics
# ---------------------------------------------------------------------------


class TestGetAdminMetrics:
    @pytest.mark.asyncio
    async def test_returns_expected_structure(self):
        admin = _make_admin()
        app = _build_app(admin)

        mock_summary = {
            "counters": {"llm_calls_total|model=gpt": 5},
            "histograms": {"llm_duration_ms|model=gpt": {"count": 5, "avg": 120}},
        }
        mock_overview = {
            "total_requests": 100,
            "total_errors": 2,
            "error_rate_percent": 2.0,
            "avg_latency_ms": 50.0,
            "latency_percentiles": {"p50_ms": 40, "p99_ms": 200},
        }

        with (
            patch("app.api.routers.admin.metrics.telemetry") as mock_tel,
            patch("app.api.routers.admin.metrics.get_metrics_store") as mock_store_fn,
        ):
            mock_tel.get_metrics_summary.return_value = mock_summary
            mock_tel.get_overview_stats.return_value = mock_overview
            mock_tel.get_service_health.return_value = {"db": {"healthy": True}}
            mock_store_fn.return_value.get_history.return_value = []

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/api/admin/metrics")

        assert resp.status_code == 200
        body = resp.json()
        assert "llm" in body
        assert "tools" in body
        assert "http" in body
        assert "missions" in body
        assert "services" in body
        assert "history" in body
        assert body["http"]["total_requests"] == 100

    @pytest.mark.asyncio
    async def test_forbidden_for_non_admin(self):
        viewer = MagicMock()
        viewer.id = "uid-viewer"
        viewer.username = "viewer"
        viewer.role = "viewer"
        viewer.is_active = True

        app = _build_app(viewer)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/admin/metrics")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /api/admin/cost-summary
# ---------------------------------------------------------------------------


class TestGetCostSummary:
    @pytest.mark.asyncio
    async def test_returns_expected_structure(self):
        admin = _make_admin()
        app = _build_app(admin)

        mock_mission = MagicMock()
        mock_mission.created_at = datetime(2025, 6, 15, tzinfo=UTC)
        mock_mission.summary = {
            "cost_data": {
                "total_cost_usd": 0.05,
                "total_tokens": 1500,
                "total_calls": 3,
                "by_agent": {
                    "scope_agent": {
                        "calls": 2,
                        "tokens": 1000,
                        "cost_usd": 0.03,
                        "errors": 0,
                    }
                },
            }
        }

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_mission]
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/admin/cost-summary")

        assert resp.status_code == 200
        body = resp.json()
        assert "period_days" in body
        assert "total_cost_usd" in body
        assert "total_tokens" in body
        assert "total_calls" in body
        assert "by_agent" in body
        assert "daily_costs" in body
        assert body["total_cost_usd"] == 0.05
        assert body["total_tokens"] == 1500
        assert body["missions_with_cost_data"] == 1

    @pytest.mark.asyncio
    async def test_empty_missions(self):
        admin = _make_admin()
        app = _build_app(admin)

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/admin/cost-summary?days=7")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_cost_usd"] == 0
        assert body["total_tokens"] == 0
        assert body["missions_with_cost_data"] == 0


# ---------------------------------------------------------------------------
# /api/admin/usage-stats
# ---------------------------------------------------------------------------


class TestGetUsageStats:
    @pytest.mark.asyncio
    async def test_returns_expected_structure(self):
        admin = _make_admin()
        app = _build_app(admin)

        mock_record = MagicMock()
        mock_record.user_id = "uid-1"
        mock_record.api_requests = 50
        mock_record.missions_started = 3
        mock_record.sandbox_minutes = 10
        mock_record.llm_tokens_used = 5000

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/admin/usage-stats")

        assert resp.status_code == 200
        body = resp.json()
        assert "period_days" in body
        assert "totals" in body
        assert "per_user" in body
        assert "unique_users" in body
        assert body["totals"]["api_requests"] == 50
        assert body["unique_users"] == 1

    @pytest.mark.asyncio
    async def test_no_usage_records(self):
        admin = _make_admin()
        app = _build_app(admin)

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/admin/usage-stats?days=7")

        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["api_requests"] == 0
        assert body["unique_users"] == 0
