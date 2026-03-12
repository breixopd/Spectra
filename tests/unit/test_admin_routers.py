"""Unit tests for admin user and plan management routers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.admin.plans import router as plans_router
from app.api.routers.admin.users import router as users_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "admin", user_id: str = "uid-1") -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.username = "admin"
    u.email = "admin@test.com"
    u.role = role
    u.is_active = True
    u.is_superuser = role == "admin"
    u.plan_id = None
    u.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    u.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    return u


def _build_app(override_user: MagicMock | None = None) -> FastAPI:
    """Build a minimal FastAPI app with admin routers and dependency overrides."""
    app = FastAPI()
    app.include_router(users_router)
    app.include_router(plans_router)

    if override_user is not None:
        from app.api.dependencies import get_current_active_user

        app.dependency_overrides[get_current_active_user] = lambda: override_user

    return app


def _mock_session():
    """Return an AsyncMock posing as an AsyncSession."""
    session = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target_user = _make_user("operator", user_id="uid-2")
        target_user.username = "operator1"
        target_user.email = "op@test.com"

        mock_sess = _mock_session()
        # count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1
        # rows query
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [target_user]

        mock_sess.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["username"] == "operator1"


class TestGetUser:
    @pytest.mark.asyncio
    async def test_get_user_found(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("operator", user_id="uid-2")
        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = target
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users/uid-2")

        assert resp.status_code == 200
        assert resp.json()["id"] == "uid-2"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users/nonexistent")

        assert resp.status_code == 404


class TestUpdateUserRole:
    @pytest.mark.asyncio
    async def test_update_role(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("operator", user_id="uid-2")
        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = target
        mock_sess.execute = AsyncMock(return_value=mock_result)
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with patch("app.api.routers.admin.users.audit_log_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/users/uid-2", json={"role": "viewer"})

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_create_plan_success(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        plan = MagicMock()
        plan.id = "plan-1"
        plan.name = "pro"
        plan.display_name = "Pro"
        plan.description = "Pro plan"
        plan.is_active = True
        plan.is_default = False
        plan.sort_order = 1
        plan.max_concurrent_missions = 5
        plan.max_missions_per_month = 100
        plan.max_targets = 50
        plan.max_api_requests_per_hour = 1000
        plan.max_api_requests_per_day = 10000
        plan.sandbox_max_containers = 3
        plan.max_storage_mb = 5000
        plan.sandbox_resource_tier = "medium"
        plan.features = {}

        mock_sess = _mock_session()
        # duplicate check returns None
        mock_dup = MagicMock()
        mock_dup.scalar_one_or_none.return_value = None
        mock_sess.execute = AsyncMock(return_value=mock_dup)
        mock_sess.add = MagicMock()
        mock_sess.flush = AsyncMock()
        mock_sess.refresh = AsyncMock()
        mock_sess.commit = AsyncMock()

        from app.core.database import get_async_session
        from app.models.plan import Plan as PlanModel

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with (
            patch("app.api.routers.admin.plans.audit_log_event", new_callable=AsyncMock),
            patch("app.api.routers.admin.plans.Plan") as MockPlan,
        ):
            instance = plan
            MockPlan.return_value = instance
            MockPlan.id = PlanModel.id
            MockPlan.name = PlanModel.name

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/admin/plans",
                    json={
                        "name": "pro",
                        "display_name": "Pro",
                        "description": "Pro plan",
                        "is_default": False,
                        "sort_order": 1,
                        "max_concurrent_missions": 5,
                        "max_missions_per_month": 100,
                        "max_targets": 50,
                        "max_api_requests_per_hour": 1000,
                        "max_api_requests_per_day": 10000,
                        "sandbox_max_containers": 3,
                        "max_storage_mb": 5000,
                        "sandbox_resource_tier": "medium",
                        "features": {},
                    },
                )

        assert resp.status_code == 201


class TestListPlans:
    @pytest.mark.asyncio
    async def test_list_plans(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        plan = MagicMock()
        plan.id = "plan-1"
        plan.name = "free"
        plan.display_name = "Free"
        plan.description = "Free tier"
        plan.is_active = True
        plan.is_default = True
        plan.sort_order = 0
        plan.max_concurrent_missions = 1
        plan.max_missions_per_month = 10
        plan.max_targets = 5
        plan.max_api_requests_per_hour = 100
        plan.max_api_requests_per_day = 1000
        plan.sandbox_max_containers = 1
        plan.max_storage_mb = 500
        plan.sandbox_resource_tier = "basic"
        plan.features = {}

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [plan]
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/plans")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "free"


class TestNonSuperuserAccessDenied:
    @pytest.mark.asyncio
    async def test_viewer_cannot_list_users(self):
        viewer = _make_user("viewer", user_id="uid-viewer")
        app = _build_app(viewer)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_operator_cannot_list_users(self):
        operator = _make_user("operator", user_id="uid-op")
        app = _build_app(operator)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_list_plans(self):
        viewer = _make_user("viewer", user_id="uid-viewer")
        app = _build_app(viewer)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/plans")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Plan update & validation
# ---------------------------------------------------------------------------


def _make_plan(**overrides):
    """Return a MagicMock that looks like a Plan ORM object."""
    defaults = dict(
        id="plan-1",
        name="pro",
        display_name="Pro",
        description="Pro plan",
        is_active=True,
        is_default=False,
        sort_order=1,
        max_concurrent_missions=5,
        max_missions_per_month=100,
        max_targets=50,
        max_api_requests_per_hour=1000,
        max_api_requests_per_day=10000,
        sandbox_max_containers=3,
        max_storage_mb=5000,
        sandbox_resource_tier="medium",
        features={},
    )
    defaults.update(overrides)
    p = MagicMock()
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


class TestUpdatePlan:
    @pytest.mark.asyncio
    async def test_update_plan_success(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        plan = _make_plan()

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_sess.execute = AsyncMock(return_value=mock_result)
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with patch("app.api.routers.admin.plans.audit_log_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/admin/plans/plan-1",
                    json={
                        "display_name": "Pro Plus",
                        "max_targets": 100,
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "pro"

    @pytest.mark.asyncio
    async def test_update_plan_not_found(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        mock_sess = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_sess.execute = AsyncMock(return_value=mock_result)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                "/api/admin/plans/nonexistent",
                json={
                    "display_name": "X",
                },
            )

        assert resp.status_code == 404


class TestCreatePlanDuplicate:
    @pytest.mark.asyncio
    async def test_create_plan_duplicate_name(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        mock_sess = _mock_session()
        mock_dup = MagicMock()
        mock_dup.scalar_one_or_none.return_value = "existing-id"
        mock_sess.execute = AsyncMock(return_value=mock_dup)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/admin/plans",
                json={
                    "name": "pro",
                    "display_name": "Pro",
                    "description": "Dup",
                    "is_default": False,
                    "sort_order": 1,
                    "max_concurrent_missions": 5,
                    "max_missions_per_month": 100,
                    "max_targets": 50,
                    "max_api_requests_per_hour": 1000,
                    "max_api_requests_per_day": 10000,
                    "sandbox_max_containers": 3,
                    "max_storage_mb": 5000,
                    "sandbox_resource_tier": "medium",
                    "features": {},
                },
            )

        assert resp.status_code == 409


class TestCreatePlanFieldValidation:
    @pytest.mark.asyncio
    async def test_missing_required_fields(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/admin/plans", json={"name": "x"})

        assert resp.status_code == 422
