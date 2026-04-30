"""Unit tests for admin user and plan management routers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.admin.plans import router as plans_router
from spectra_api.api.routers.admin.users import router as users_router
from app.models.audit_log import AuditEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "admin", user_id: str = "00000000-0000-4000-a000-000000000001") -> MagicMock:
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
        from spectra_api.api.dependencies import get_current_active_user

        app.dependency_overrides[get_current_active_user] = lambda: override_user

    return app


def _mock_session():
    """Return an AsyncMock posing as an AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()  # sync method — avoid AsyncMock coroutine warning
    return session


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target_user = _make_user("user", user_id="00000000-0000-4000-a000-000000000002")
        target_user.username = "user1"
        target_user.email = "user@test.com"

        mock_sess = _mock_session()
        # count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1
        # rows query
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [target_user]
        mock_plan_map = MagicMock()
        mock_plan_map.all.return_value = []

        mock_sess.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result, mock_plan_map])

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["username"] == "user1"


class TestGetUser:
    @pytest.mark.asyncio
    async def test_get_user_found(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000002")
        mock_sess = _mock_session()
        mock_lookup = MagicMock()
        mock_lookup.scalar_one_or_none.return_value = target
        mock_plan_map = MagicMock()
        mock_plan_map.all.return_value = [(target.id, "subscription-plan-id")]
        mock_sess.execute = AsyncMock(side_effect=[mock_lookup, mock_plan_map])

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users/00000000-0000-4000-a000-000000000002")

        assert resp.status_code == 200
        assert resp.json()["id"] == "00000000-0000-4000-a000-000000000002"
        assert resp.json()["plan_id"] == "subscription-plan-id"

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
            resp = await ac.get("/api/admin/users/00000000-0000-4000-a000-000000000099")

        assert resp.status_code == 404


class TestUpdateUserRole:
    @pytest.mark.asyncio
    async def test_update_role(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000002")
        mock_sess = _mock_session()
        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = target
        before_plan_map = MagicMock()
        before_plan_map.all.return_value = []
        before_subscription = MagicMock()
        before_subscription.scalar_one_or_none.return_value = None
        after_plan_map = MagicMock()
        after_plan_map.all.return_value = []
        response_plan_map = MagicMock()
        response_plan_map.all.return_value = []
        mock_sess.execute = AsyncMock(
            side_effect=[lookup_result, before_subscription, before_plan_map, after_plan_map, response_plan_map]
        )
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with patch("spectra_api.api.routers.admin.users.audit_log_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/users/00000000-0000-4000-a000-000000000002", json={"role": "staff"})

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_email_logs_settings_changed_without_snapshot(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000002")
        mock_sess = _mock_session()

        mock_lookup = MagicMock()
        mock_lookup.scalar_one_or_none.return_value = target
        mock_duplicate = MagicMock()
        mock_duplicate.scalar_one_or_none.return_value = None
        before_plan_map = MagicMock()
        before_plan_map.all.return_value = [(target.id, "existing-plan")]
        before_subscription = MagicMock()
        before_subscription.scalar_one_or_none.return_value = MagicMock(
            plan_id="existing-plan",
            status="active",
            trial_ends_at=None,
            current_period_start=datetime(2025, 1, 1, tzinfo=UTC),
            current_period_end=None,
            external_subscription_id=None,
            external_customer_id=None,
            payment_provider="manual",
            metadata_=None,
        )
        after_plan_map = MagicMock()
        after_plan_map.all.return_value = [(target.id, "existing-plan")]
        response_plan_map = MagicMock()
        response_plan_map.all.return_value = [(target.id, "existing-plan")]

        mock_sess.execute = AsyncMock(
            side_effect=[
                mock_lookup,
                before_subscription,
                before_plan_map,
                mock_duplicate,
                after_plan_map,
                response_plan_map,
            ]
        )
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with (
            patch("spectra_api.api.routers.admin.users.audit_log_event", new_callable=AsyncMock) as audit_mock,
            patch("spectra_api.api.routers.admin.users.create_snapshot", new_callable=AsyncMock) as snapshot_mock,
            patch("spectra_api.api.routers.admin.users._sync_user_subscription_assignment", new_callable=AsyncMock) as sync_mock,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/admin/users/00000000-0000-4000-a000-000000000002",
                    json={"email": "updated@test.com", "plan_id": "existing-plan"},
                )

        assert resp.status_code == 200
        snapshot_mock.assert_not_awaited()
        sync_mock.assert_not_awaited()
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.args[1] == AuditEventType.SETTINGS_CHANGED
        assert audit_mock.await_args.kwargs["details"] == {
            "action": "user_updated",
            "target_user": target.username,
            "changed_fields": ["email"],
        }


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_create_user_returns_activation_url_when_delivery_fails_and_starts_inactive(self):
        import spectra_api.api.routers.admin.users as users_module

        admin = _make_user("admin")
        app = _build_app(admin)
        mock_sess = _mock_session()

        duplicate_check = MagicMock()
        duplicate_check.scalar_one_or_none.return_value = None
        no_subscription = MagicMock()
        no_subscription.scalar_one_or_none.return_value = None
        plan_map = MagicMock()
        plan_map.all.return_value = []
        mock_sess.execute = AsyncMock(side_effect=[duplicate_check, no_subscription, plan_map])
        mock_sess.flush = AsyncMock()
        mock_sess.commit = AsyncMock()

        created = {}

        def add_user(user):
            user.id = "uid-new"
            user.created_at = datetime(2025, 1, 1, tzinfo=UTC)
            user.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
            created["user"] = user

        mock_sess.add = MagicMock(side_effect=add_user)
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with (
            patch("spectra_api.api.routers.admin.users.audit_log_event", new_callable=AsyncMock),
            patch.object(type(users_module.settings), "smtp_configured", new_callable=PropertyMock, return_value=True),
            patch(
                "app.services.auth.email_verification.send_registration_verification_email", new=AsyncMock(return_value=False)
            ) as send_mock,
            patch(
                "app.services.auth.email_verification.build_email_verification_url",
                return_value="http://test/verify-email?token=abc123",
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/admin/users",
                    json={
                        "username": "pending-user",
                        "email": "pending@example.com",
                        "password": "StrongPass1",
                        "role": "user",
                    },
                )

        assert resp.status_code == 201
        body = resp.json()
        assert body["activation_url"] == "http://test/verify-email?token=abc123"
        assert created["user"].is_active is False
        assert created["user"].email_verified is False
        send_mock.assert_awaited_once()


class TestSubscriptionBackedAssignments:
    @pytest.mark.asyncio
    async def test_remote_stripe_override_skips_rollback_snapshot_creation(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000016")
        target.email_verified = True

        stripe_subscription = MagicMock(
            plan_id="plan-old",
            status="active",
            trial_ends_at=None,
            current_period_start=datetime(2026, 4, 1, tzinfo=UTC),
            current_period_end=None,
            external_subscription_id="sub_123",
            external_customer_id="cus_123",
            payment_provider="stripe",
            metadata_=None,
        )

        mock_sess = _mock_session()
        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = target
        before_subscription = MagicMock()
        before_subscription.scalar_one_or_none.return_value = stripe_subscription
        before_plan_map = MagicMock()
        before_plan_map.all.return_value = [(target.id, "plan-old")]
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = None
        after_plan_map = MagicMock()
        after_plan_map.all.return_value = [(target.id, "plan-new")]
        response_plan_map = MagicMock()
        response_plan_map.all.return_value = [(target.id, "plan-new")]
        mock_sess.execute = AsyncMock(
            side_effect=[
                lookup_result,
                before_subscription,
                before_plan_map,
                duplicate_result,
                after_plan_map,
                response_plan_map,
            ]
        )
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with (
            patch("spectra_api.api.routers.admin.users.audit_log_event", new_callable=AsyncMock),
            patch("spectra_api.api.routers.admin.users.create_snapshot", new_callable=AsyncMock) as snapshot_mock,
            patch("spectra_api.api.routers.admin.users._sync_user_subscription_assignment", new_callable=AsyncMock) as sync_mock,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/admin/users/00000000-0000-4000-a000-000000000016",
                    json={"plan_id": "plan-new", "email": "stripe-override@test.com"},
                )

        assert resp.status_code == 200
        snapshot_mock.assert_not_awaited()
        sync_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_plan_change_rejects_duplicate_email_before_subscription_sync(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000017")
        target.email_verified = True

        stripe_subscription = MagicMock(
            plan_id="plan-old",
            status="active",
            trial_ends_at=None,
            current_period_start=datetime(2026, 4, 1, tzinfo=UTC),
            current_period_end=None,
            external_subscription_id="sub_123",
            external_customer_id="cus_123",
            payment_provider="stripe",
            metadata_=None,
        )

        mock_sess = _mock_session()
        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = target
        before_subscription = MagicMock()
        before_subscription.scalar_one_or_none.return_value = stripe_subscription
        before_plan_map = MagicMock()
        before_plan_map.all.return_value = [(target.id, "plan-old")]
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = "other-user-id"
        mock_sess.execute = AsyncMock(
            side_effect=[lookup_result, before_subscription, before_plan_map, duplicate_result]
        )

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with patch(
            "spectra_api.api.routers.admin.users._sync_user_subscription_assignment",
            new_callable=AsyncMock,
        ) as sync_mock:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/admin/users/00000000-0000-4000-a000-000000000017",
                    json={"plan_id": "plan-new", "email": "admin@test.com"},
                )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Email already in use"
        sync_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_validates_plan_before_remote_cancel(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000018")
        mock_sess = _mock_session()

        with (
            patch(
                "spectra_api.api.routers.admin.users._validate_plan_or_404",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Plan not found")),
            ) as validate_mock,
            patch(
                "spectra_api.api.routers.admin.users.PaymentService.cancel_external_subscription",
                new=AsyncMock(),
            ) as cancel_mock,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _sync_user_subscription_assignment(mock_sess, user, "missing-plan")

        assert exc_info.value.status_code == 404
        validate_mock.assert_awaited_once_with(mock_sess, "missing-plan")
        mock_sess.execute.assert_not_awaited()
        cancel_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_creates_active_subscription(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment
        from app.models.plan import Subscription

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000010")
        mock_sess = _mock_session()

        no_sub = MagicMock()
        no_sub.scalar_one_or_none.return_value = None
        plan_lookup = MagicMock()
        plan_lookup.scalar_one_or_none.return_value = MagicMock(id="plan-123")
        mock_sess.execute = AsyncMock(side_effect=[plan_lookup, no_sub])

        with patch("spectra_api.api.routers.admin.users.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock:
            await _sync_user_subscription_assignment(mock_sess, user, "plan-123")

        added = mock_sess.add.call_args.args[0]
        assert isinstance(added, Subscription)
        assert added.plan_id == "plan-123"
        assert added.status == "active"
        mirror_mock.assert_awaited_once_with(mock_sess, user=user)

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_cancels_existing_subscription(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000011")
        existing_sub = MagicMock()
        existing_sub.status = "active"
        existing_sub.payment_provider = "stripe"
        existing_sub.current_period_end = None
        existing_sub.external_subscription_id = "sub_123"
        existing_sub.external_customer_id = "cus_123"
        existing_sub.metadata_ = {"source": "stripe"}

        sub_lookup = MagicMock()
        sub_lookup.scalar_one_or_none.return_value = existing_sub
        mock_sess = _mock_session()
        mock_sess.execute = AsyncMock(return_value=sub_lookup)

        with (
            patch("spectra_api.api.routers.admin.users.PaymentService.cancel_external_subscription", new=AsyncMock(return_value=True)) as cancel_mock,
            patch("spectra_api.api.routers.admin.users.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock,
        ):
            await _sync_user_subscription_assignment(mock_sess, user, None)

        cancel_mock.assert_awaited_once_with(existing_sub)
        assert existing_sub.status == "cancelled"
        assert existing_sub.current_period_end is not None
        assert existing_sub.payment_provider == "manual"
        assert existing_sub.external_subscription_id is None
        assert existing_sub.external_customer_id is None
        assert existing_sub.metadata_ is None
        mirror_mock.assert_awaited_once_with(mock_sess, user=user)

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_detaches_existing_stripe_subscription(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000013")
        existing_sub = MagicMock()
        existing_sub.plan_id = "plan-old"
        existing_sub.status = "past_due"
        existing_sub.payment_provider = "stripe"
        existing_sub.current_period_end = datetime(2025, 1, 2, tzinfo=UTC)
        existing_sub.external_subscription_id = "sub_456"
        existing_sub.external_customer_id = "cus_456"
        existing_sub.metadata_ = {"source": "stripe"}

        sub_lookup = MagicMock()
        sub_lookup.scalar_one_or_none.return_value = existing_sub
        plan_lookup = MagicMock()
        plan_lookup.scalar_one_or_none.return_value = MagicMock(id="plan-new")
        mock_sess = _mock_session()
        mock_sess.execute = AsyncMock(side_effect=[plan_lookup, sub_lookup])

        with (
            patch("spectra_api.api.routers.admin.users.PaymentService.cancel_external_subscription", new=AsyncMock(return_value=True)) as cancel_mock,
            patch("spectra_api.api.routers.admin.users.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock,
        ):
            await _sync_user_subscription_assignment(mock_sess, user, "plan-new")

        cancel_mock.assert_awaited_once_with(existing_sub)
        assert existing_sub.plan_id == "plan-new"
        assert existing_sub.status == "active"
        assert existing_sub.payment_provider == "manual"
        assert existing_sub.external_subscription_id is None
        assert existing_sub.external_customer_id is None
        assert existing_sub.metadata_ is None
        mirror_mock.assert_awaited_once_with(mock_sess, user=user)

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_blocks_manual_override_when_remote_cancel_fails(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000014")
        existing_sub = MagicMock()
        existing_sub.plan_id = "plan-old"
        existing_sub.status = "active"
        existing_sub.payment_provider = "stripe"
        existing_sub.current_period_end = None
        existing_sub.external_subscription_id = "sub_blocked"
        existing_sub.external_customer_id = "cus_blocked"
        existing_sub.metadata_ = {"source": "stripe"}

        sub_lookup = MagicMock()
        sub_lookup.scalar_one_or_none.return_value = existing_sub
        mock_sess = _mock_session()
        mock_sess.execute = AsyncMock(return_value=sub_lookup)

        with (
            patch("spectra_api.api.routers.admin.users.PaymentService.cancel_external_subscription", new=AsyncMock(return_value=False)),
            patch("spectra_api.api.routers.admin.users.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _sync_user_subscription_assignment(mock_sess, user, None)

        assert exc_info.value.status_code == 502
        assert existing_sub.status == "active"
        assert existing_sub.payment_provider == "stripe"
        assert existing_sub.external_subscription_id == "sub_blocked"
        assert existing_sub.external_customer_id == "cus_blocked"
        mirror_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_user_subscription_assignment_blocks_detach_without_external_subscription_id(self):
        from spectra_api.api.routers.admin.users import _sync_user_subscription_assignment

        user = _make_user("user", user_id="00000000-0000-4000-a000-000000000015")
        existing_sub = MagicMock()
        existing_sub.plan_id = "plan-old"
        existing_sub.status = "active"
        existing_sub.payment_provider = "stripe"
        existing_sub.current_period_end = None
        existing_sub.external_subscription_id = None
        existing_sub.external_customer_id = "cus_only"
        existing_sub.metadata_ = {"source": "stripe"}

        sub_lookup = MagicMock()
        sub_lookup.scalar_one_or_none.return_value = existing_sub
        mock_sess = _mock_session()
        mock_sess.execute = AsyncMock(return_value=sub_lookup)

        with patch("spectra_api.api.routers.admin.users.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock:
            with pytest.raises(HTTPException) as exc_info:
                await _sync_user_subscription_assignment(mock_sess, user, None)

        assert exc_info.value.status_code == 409
        assert existing_sub.payment_provider == "stripe"
        assert existing_sub.external_customer_id == "cus_only"
        mirror_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_effective_plan_does_not_trigger_subscription_sync(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000012")
        mock_sess = _mock_session()

        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = target
        before_subscription = MagicMock()
        before_subscription.scalar_one_or_none.return_value = None
        before_plan_map = MagicMock()
        before_plan_map.all.return_value = [(target.id, "plan-123")]
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = None
        after_plan_map = MagicMock()
        after_plan_map.all.return_value = [(target.id, "plan-123")]
        response_plan_map = MagicMock()
        response_plan_map.all.return_value = [(target.id, "plan-123")]
        mock_sess.execute = AsyncMock(
            side_effect=[
                lookup_result,
                before_subscription,
                before_plan_map,
                duplicate_result,
                after_plan_map,
                response_plan_map,
            ]
        )
        mock_sess.commit = AsyncMock()
        mock_sess.refresh = AsyncMock()

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with (
            patch("spectra_api.api.routers.admin.users.audit_log_event", new_callable=AsyncMock),
            patch("spectra_api.api.routers.admin.users.create_snapshot", new_callable=AsyncMock) as snapshot_mock,
            patch("spectra_api.api.routers.admin.users._sync_user_subscription_assignment", new_callable=AsyncMock) as sync_mock,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/admin/users/00000000-0000-4000-a000-000000000012",
                    json={"plan_id": "plan-123", "email": "admin+unchanged@test.com"},
                )

        assert resp.status_code == 200
        snapshot_mock.assert_not_awaited()
        sync_mock.assert_not_awaited()


class TestPendingActivationGuard:
    @pytest.mark.asyncio
    async def test_update_user_cannot_activate_before_verification(self):
        admin = _make_user("admin")
        app = _build_app(admin)

        target = _make_user("user", user_id="00000000-0000-4000-a000-000000000002")
        target.is_active = False
        target.email_verified = False

        mock_sess = _mock_session()
        lookup = MagicMock()
        lookup.scalar_one_or_none.return_value = target
        mock_sess.execute = AsyncMock(return_value=lookup)

        from app.core.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_sess

        with patch("spectra_api.api.routers.admin.users.create_snapshot", new_callable=AsyncMock) as snapshot_mock:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/users/00000000-0000-4000-a000-000000000002", json={"is_active": True})

        assert resp.status_code == 400
        assert "activation" in resp.json()["detail"].lower()
        snapshot_mock.assert_not_awaited()


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
            patch("spectra_api.api.routers.admin.plans.audit_log_event", new_callable=AsyncMock),
            patch("spectra_api.api.routers.admin.plans.Plan") as MockPlan,
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
    async def test_user_cannot_list_users(self):
        user = _make_user("user", user_id="uid-user")
        app = _build_app(user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/users")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_staff_cannot_list_plans(self):
        staff = _make_user("staff", user_id="uid-staff")
        app = _build_app(staff)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/plans")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_cannot_list_plans(self):
        user = _make_user("user", user_id="uid-user")
        app = _build_app(user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/plans")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Plan update & validation
# ---------------------------------------------------------------------------


def _make_plan(**overrides):
    """Return a MagicMock that looks like a Plan ORM object."""
    defaults = {
        "id": "plan-1",
        "name": "pro",
        "display_name": "Pro",
        "description": "Pro plan",
        "is_active": True,
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
    }
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

        with patch("spectra_api.api.routers.admin.plans.audit_log_event", new_callable=AsyncMock):
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
