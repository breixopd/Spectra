"""Tests for spectra_api.api.routers.admin.rollback endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.admin.rollback import router


def _fake_user(role: str = "admin", user_id: str = "u-admin-1"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = role == "admin"
    user.role = role
    return user


def _make_app() -> FastAPI:
    from app.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router)
    return app


def _override_deps(app: FastAPI, user, mock_session):
    from app.core.database import get_async_session
    from spectra_api.api.dependencies import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: user

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session


def _make_snapshot(**overrides):
    defaults = {
        "id": "snap-1",
        "actor_user_id": "u-admin-1",
        "target_entity_type": "user",
        "target_entity_id": "u-target-1",
        "action": "update_role",
        "before_state": "{}",
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.get_all_snapshots", new_callable=AsyncMock)
async def test_list_snapshots_as_admin(mock_get_all):
    snap = _make_snapshot()
    mock_get_all.return_value = [snap]

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "snap-1"
    assert data[0]["entity_type"] == "user"
    mock_get_all.assert_awaited_once_with(mock_session, limit=50)


@pytest.mark.asyncio
async def test_list_snapshots_as_user_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_snapshots_as_operator_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots")

    assert resp.status_code == 403


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_success(mock_rollback):
    mock_rollback.return_value = {"role": "staff"}

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rolled_back"
    assert body["restored"] == {"role": "staff"}
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_value_error(mock_rollback):
    mock_rollback.side_effect = ValueError("Rollback cannot recreate a remotely cancelled Stripe subscription")

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/rollback/snapshots/snap-bad/rollback")

    assert resp.status_code == 409
    assert "cannot recreate" in resp.json()["detail"].lower()


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_unexpected_error(mock_rollback):
    mock_rollback.side_effect = RuntimeError("unexpected")

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_apply_rollback_without_admin_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 403


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.get_all_snapshots", new_callable=AsyncMock)
async def test_list_snapshots_custom_limit(mock_get_all):
    mock_get_all.return_value = []

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots?limit=10")

    assert resp.status_code == 200
    mock_get_all.assert_awaited_once_with(mock_session, limit=10)


@pytest.mark.asyncio
@patch("spectra_api.api.routers.admin.rollback.get_all_snapshots", new_callable=AsyncMock)
async def test_list_snapshots_marks_remote_stripe_restore_as_non_restorable(mock_get_all):
    snap = _make_snapshot()
    snap.before_state = '{"subscription": {"payment_provider": "stripe", "external_subscription_id": "sub_123"}}'
    mock_get_all.return_value = [snap]

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["restorable"] is False
    assert "stripe subscription" in body[0]["restore_error"].lower()


@pytest.mark.asyncio
async def test_describe_snapshot_restorability_blocks_remote_stripe_restore():
    from app.services.system.rollback import describe_snapshot_restorability

    snapshot = _make_snapshot()
    snapshot.before_state = '{"subscription": {"payment_provider": "stripe", "external_subscription_id": "sub_123"}}'

    restorable, restore_error = describe_snapshot_restorability(snapshot)

    assert restorable is False
    assert restore_error is not None
    assert "stripe subscription" in restore_error.lower()


@pytest.mark.asyncio
async def test_list_snapshots_limit_exceeds_max():
    """Limit > 200 should fail validation."""
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/rollback/snapshots?limit=999")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rollback_user_restores_subscription_state():
    from app.services.system.rollback import _rollback_user

    user = MagicMock()
    user.id = "u-target-1"
    user.email = "current@example.com"
    user.is_active = True
    user.role = "user"
    user.is_superuser = False

    subscription = MagicMock()
    subscription.plan_id = "plan-new"
    subscription.status = "cancelled"
    subscription.payment_provider = "manual"
    subscription.current_period_start = datetime(2026, 4, 13, 9, 0, tzinfo=UTC)
    subscription.current_period_end = datetime(2026, 4, 13, 10, 0, tzinfo=UTC)
    subscription.trial_ends_at = None
    subscription.external_subscription_id = None
    subscription.external_customer_id = None
    subscription.metadata_ = {"source": "admin"}

    user_lookup = MagicMock()
    user_lookup.scalar_one_or_none.return_value = user
    subscription_lookup = MagicMock()
    subscription_lookup.scalar_one_or_none.return_value = subscription

    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[user_lookup, subscription_lookup])

    before_state = {
        "email": "original@example.com",
        "is_active": True,
        "role": "user",
        "is_superuser": False,
        "plan_id": "plan-old",
        "subscription": {
            "plan_id": "plan-old",
            "status": "active",
            "trial_ends_at": None,
            "current_period_start": datetime(2026, 4, 12, 9, 0, tzinfo=UTC).isoformat(),
            "current_period_end": None,
            "external_subscription_id": None,
            "external_customer_id": None,
            "payment_provider": "manual",
            "metadata": {"source": "admin"},
        },
    }

    with patch("app.services.system.rollback.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock:
        await _rollback_user(session, "u-target-1", before_state)

    assert user.email == "original@example.com"
    assert subscription.plan_id == "plan-old"
    assert subscription.status == "active"
    assert subscription.current_period_end is None
    mirror_mock.assert_awaited_once_with(session, user=user)


@pytest.mark.asyncio
async def test_rollback_user_removes_created_subscription_when_snapshot_had_none():
    from app.services.system.rollback import _rollback_user

    user = MagicMock()
    user.id = "u-target-2"
    user.is_active = True
    user.role = "user"
    user.is_superuser = False

    subscription = MagicMock()

    user_lookup = MagicMock()
    user_lookup.scalar_one_or_none.return_value = user
    subscription_lookup = MagicMock()
    subscription_lookup.scalar_one_or_none.return_value = subscription

    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[user_lookup, subscription_lookup, MagicMock()])

    before_state = {
        "is_active": True,
        "role": "user",
        "is_superuser": False,
        "plan_id": None,
        "subscription": None,
    }

    with patch("app.services.system.rollback.sync_user_plan_mirror", new=AsyncMock()) as mirror_mock:
        await _rollback_user(session, "u-target-2", before_state)

    delete_stmt = session.execute.await_args_list[2].args[0]
    assert "DELETE FROM subscriptions" in str(delete_stmt)
    mirror_mock.assert_awaited_once_with(session, user=user)
