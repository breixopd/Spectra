"""Tests for API key management — generate, list, revoke, per-user limits."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.repositories.api_key import ApiKeyRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_api_key(
    *,
    key_id: str = "k-1",
    user_id: str = "u-1",
    name: str = "default",
    key_prefix: str = "sk-abcde",
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> MagicMock:
    k = MagicMock()
    k.id = key_id
    k.user_id = user_id
    k.name = name
    k.key_prefix = key_prefix
    k.key_hash = hashlib.sha256(b"sk-test").hexdigest()
    k.is_active = is_active
    k.created_at = datetime.now(UTC)
    k.last_used_at = None
    k.expires_at = expires_at
    return k


def _mock_user(user_id: str = "u-1") -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.username = "tester"
    u.is_active = True
    u.is_superuser = False
    return u


def _mock_request() -> MagicMock:
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {}
    req.url = MagicMock()
    req.url.path = "/api/v1/auth/api-keys"
    return req


# ---------------------------------------------------------------------------
# Create API key endpoint
# ---------------------------------------------------------------------------


class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_generates_key_with_sk_prefix(self):
        from app.api.routers.auth import CreateApiKeyRequest, create_api_key

        user = _mock_user()
        session = AsyncMock()
        session.commit = AsyncMock()
        mock_key = _mock_api_key()

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_active_by_user = AsyncMock(return_value=[])
            repo_instance.create = AsyncMock(return_value=mock_key)

            result = await create_api_key(
                request=_mock_request(),
                body=CreateApiKeyRequest(name="my-key"),
                current_user=user,
                session=session,
            )

        assert result["name"] == mock_key.name
        assert result["key"].startswith("sk-")
        assert len(result["key"]) > 20
        assert "prefix" in result
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enforces_max_10_keys_per_user(self):
        from app.api.routers.auth import CreateApiKeyRequest, create_api_key

        user = _mock_user()
        session = AsyncMock()
        existing_keys = [_mock_api_key(key_id=f"k-{i}") for i in range(10)]

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_active_by_user = AsyncMock(return_value=existing_keys)

            with pytest.raises(HTTPException) as exc_info:
                await create_api_key(
                    request=_mock_request(),
                    body=CreateApiKeyRequest(name="one-too-many"),
                    current_user=user,
                    session=session,
                )
            assert exc_info.value.status_code == 400
            assert "10" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_expiration_set_when_requested(self):
        from app.api.routers.auth import CreateApiKeyRequest, create_api_key

        user = _mock_user()
        session = AsyncMock()
        session.commit = AsyncMock()
        mock_key = _mock_api_key(expires_at=datetime.now(UTC) + timedelta(days=30))

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_active_by_user = AsyncMock(return_value=[])
            repo_instance.create = AsyncMock(return_value=mock_key)

            result = await create_api_key(
                request=_mock_request(),
                body=CreateApiKeyRequest(name="expiring", expires_in_days=30),
                current_user=user,
                session=session,
            )

        assert result["expires_at"] is not None
        # Verify create was called with expires_at
        call_kwargs = repo_instance.create.call_args[1]
        assert call_kwargs["expires_at"] is not None


# ---------------------------------------------------------------------------
# Revoke API key endpoint
# ---------------------------------------------------------------------------


class TestRevokeApiKey:
    @pytest.mark.asyncio
    async def test_revokes_own_key(self):
        from app.api.routers.auth import revoke_api_key

        user = _mock_user(user_id="u-1")
        key = _mock_api_key(user_id="u-1", key_id="k-1")
        session = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=key)
            repo_instance.deactivate = AsyncMock()

            result = await revoke_api_key(
                key_id="k-1",
                request=_mock_request(),
                current_user=user,
                session=session,
            )

        assert "revoked" in result["message"].lower()
        repo_instance.deactivate.assert_awaited_once_with("k-1")
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cannot_revoke_other_users_key(self):
        from app.api.routers.auth import revoke_api_key

        user = _mock_user(user_id="u-1")
        key = _mock_api_key(user_id="u-OTHER")
        session = AsyncMock()

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=key)

            with pytest.raises(HTTPException) as exc_info:
                await revoke_api_key(
                    key_id="k-1",
                    request=_mock_request(),
                    current_user=user,
                    session=session,
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self):
        from app.api.routers.auth import revoke_api_key

        user = _mock_user()
        session = AsyncMock()

        with (
            patch("app.repositories.api_key.ApiKeyRepository") as MockRepo,
            patch("app.api.routers.auth.audit_log_event", new_callable=AsyncMock),
        ):
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await revoke_api_key(
                    key_id="nonexistent",
                    request=_mock_request(),
                    current_user=user,
                    session=session,
                )
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# List API keys endpoint
# ---------------------------------------------------------------------------


class TestListApiKeys:
    @pytest.mark.asyncio
    async def test_returns_masked_keys(self):
        from app.api.routers.auth import list_api_keys

        user = _mock_user()
        keys = [_mock_api_key(key_id="k-1", name="prod"), _mock_api_key(key_id="k-2", name="dev")]
        session = AsyncMock()

        with patch("app.repositories.api_key.ApiKeyRepository") as MockRepo:
            repo_instance = MockRepo.return_value
            repo_instance.get_by_user_id = AsyncMock(return_value=keys)

            result = await list_api_keys(current_user=user, session=session)

        assert len(result) == 2
        assert result[0]["id"] == "k-1"
        # No raw key should be exposed
        for item in result:
            assert "key" not in item or not item.get("key", "").startswith("sk-")
            assert "key_prefix" in item


# ---------------------------------------------------------------------------
# ApiKeyRepository basic operations
# ---------------------------------------------------------------------------


class TestApiKeyRepositoryOps:
    @pytest.mark.asyncio
    async def test_deactivate_calls_update(self):
        session = AsyncMock()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "update", new_callable=AsyncMock) as mock_update:
            await repo.deactivate("k-99")
        mock_update.assert_awaited_once_with("k-99", is_active=False)

    @pytest.mark.asyncio
    async def test_get_by_prefix_delegates(self):
        session = AsyncMock()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value=None) as mock_find:
            result = await repo.get_by_prefix("sk-abcd")
        mock_find.assert_awaited_once_with(key_prefix="sk-abcd")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_by_user_filters(self):
        session = AsyncMock()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=[]) as mock_find:
            result = await repo.get_active_by_user("u-1")
        mock_find.assert_awaited_once_with(user_id="u-1", is_active=True, skip=0, limit=100)
        assert result == []
