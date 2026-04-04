"""Additional edge case tests for RBAC, encryption, token blacklist, and lockout."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.routers.auth import (
    LOCKOUT_THRESHOLD_1,
    LOCKOUT_THRESHOLD_2,
    _check_lockout,
    _record_failure,
)
from app.core.encryption import (
    decrypt_field,
    decrypt_sensitive_fields,
    encrypt_field,
    encrypt_sensitive_fields,
    is_sensitive_key,
)
from app.core.rbac import ROLE_PERMISSIONS, Permission, has_permission
from app.core.security import (
    _blacklist_lock,
    _blacklisted_tokens,
    _user_token_blacklist,
    create_access_token,
    invalidate_token,
    is_token_blacklisted,
)

# --- RBAC Permission Tests ---


class TestRBACPermissions:
    def test_admin_has_all_permissions(self):
        for perm in Permission:
            assert has_permission("admin", perm), f"Admin missing {perm}"

    def test_viewer_cannot_write(self):
        write_perms = [
            Permission.CREATE_MISSIONS,
            Permission.MANAGE_MISSIONS,
            Permission.MANAGE_FINDINGS,
            Permission.MANAGE_TARGETS,
            Permission.USE_TOOLS,
            Permission.MANAGE_SETTINGS,
            Permission.MANAGE_USERS,
        ]
        for perm in write_perms:
            assert not has_permission("viewer", perm), f"Viewer should not have {perm}"

    def test_viewer_can_read(self):
        read_perms = [
            Permission.VIEW_MISSIONS,
            Permission.VIEW_FINDINGS,
            Permission.VIEW_TARGETS,
            Permission.VIEW_REPORTS,
        ]
        for perm in read_perms:
            assert has_permission("viewer", perm), f"Viewer missing {perm}"

    def test_operator_can_do_missions(self):
        assert has_permission("operator", Permission.CREATE_MISSIONS)
        assert has_permission("operator", Permission.MANAGE_MISSIONS)
        assert has_permission("operator", Permission.USE_TOOLS)

    def test_operator_cannot_manage_settings(self):
        assert not has_permission("operator", Permission.MANAGE_SETTINGS)
        assert not has_permission("operator", Permission.MANAGE_USERS)

    def test_operator_can_view_audit_log(self):
        # Operators can view their own audit log; this is intentional
        assert has_permission("operator", Permission.VIEW_AUDIT_LOG)

    def test_unknown_role_has_no_permissions(self):
        for perm in Permission:
            assert not has_permission("unknown_role", perm)

    def test_role_permissions_dict_has_expected_roles(self):
        assert "admin" in ROLE_PERMISSIONS
        assert "operator" in ROLE_PERMISSIONS
        assert "viewer" in ROLE_PERMISSIONS


# --- Encryption Tests ---


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        sREDACTED_SECRET_3161cd504855
        original = "sensitive data here"
        encrypted = encrypt_field(original, secret)
        decrypted = decrypt_field(encrypted, secret)
        assert decrypted == original
        assert encrypted != original

    def test_encrypt_unicode(self):
        secret = "key"
        original = "données sensibles 🔒"
        encrypted = encrypt_field(original, secret)
        decrypted = decrypt_field(encrypted, secret)
        assert decrypted == original

    def test_encrypt_empty_string(self):
        secret = "key"
        encrypted = encrypt_field("", secret)
        decrypted = decrypt_field(encrypted, secret)
        assert decrypted == ""

    def test_different_secrets_incompatible(self):
        encrypted = encrypt_field("data", "key1")
        with pytest.raises((ValueError, TypeError, Exception)):  # noqa: B017
            decrypt_field(encrypted, "key2")

    def test_is_sensitive_key_true(self):
        assert is_sensitive_key("password")
        assert is_sensitive_key("db_password")
        assert is_sensitive_key("api_key")
        assert is_sensitive_key("secret_token")
        assert is_sensitive_key("user_credential")

    def test_is_sensitive_key_false(self):
        assert not is_sensitive_key("username")
        assert not is_sensitive_key("host")
        assert not is_sensitive_key("port")

    def test_encrypt_sensitive_fields(self):
        data = {
            "host": "localhost",
            "password": "mysecret",
            "api_key": "key123",
            "port": 5432,
        }
        encrypted = encrypt_sensitive_fields(data, "secret")
        assert encrypted["host"] == "localhost"
        assert encrypted["port"] == 5432
        assert encrypted["password"] != "mysecret"
        assert encrypted["api_key"] != "key123"

    def test_decrypt_sensitive_fields(self):
        data = {
            "host": "localhost",
            "password": "mysecret",
            "api_key": "key123",
        }
        encrypted = encrypt_sensitive_fields(data, "secret")
        decrypted = decrypt_sensitive_fields(encrypted, "secret")
        assert decrypted["password"] == "mysecret"
        assert decrypted["api_key"] == "key123"
        assert decrypted["host"] == "localhost"

    def test_encrypt_skips_already_encrypted(self):
        data = {"password": "gAAAAA_already_encrypted_data"}
        encrypted = encrypt_sensitive_fields(data, "secret")
        assert encrypted["password"] == "gAAAAA_already_encrypted_data"

    def test_encrypt_nested_dict(self):
        data = {
            "config": {
                "db_password": "secret123",
                "host": "localhost",
            }
        }
        encrypted = encrypt_sensitive_fields(data, "key")
        assert encrypted["config"]["host"] == "localhost"
        assert encrypted["config"]["db_password"] != "secret123"

    def test_decrypt_invalid_token_returns_as_is(self):
        data = {"password": "not-a-valid-fernet-token"}
        result = decrypt_sensitive_fields(data, "key")
        assert result["password"] == "not-a-valid-fernet-token"


# --- Token Blacklist Extended Tests ---


@pytest.fixture(autouse=True)
def _clear_blacklist_state():
    """Clear in-memory token blacklist state between tests."""
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()


class TestTokenBlacklistExtended:
    def test_multiple_tokens_blacklisted(self):
        t1 = create_access_token(data={"sub": "user1"})
        t2 = create_access_token(data={"sub": "user2"})
        invalidate_token(t1)
        invalidate_token(t2)
        assert is_token_blacklisted(t1)
        assert is_token_blacklisted(t2)

    def test_blacklist_does_not_affect_other_tokens(self):
        t1 = create_access_token(data={"sub": "user1"})
        t2 = create_access_token(data={"sub": "user2"})
        invalidate_token(t1)
        assert is_token_blacklisted(t1)
        assert not is_token_blacklisted(t2)


# --- Account Lockout Tests (DB-based) ---


def _make_user(fail_count=0, locked_until=None):
    """Create a mock User object for lockout testing."""
    user = MagicMock()
    user.login_fail_count = fail_count
    user.locked_until = locked_until
    return user


class TestAccountLockout:
    @pytest.mark.asyncio
    async def test_check_lockout_raises_when_locked(self):
        now = datetime.now(UTC)
        user = _make_user(locked_until=now + timedelta(minutes=5))
        with pytest.raises(HTTPException) as exc:
            await _check_lockout(user)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_check_lockout_passes_when_not_locked(self):
        user = _make_user(locked_until=None)
        await _check_lockout(user)  # Should not raise

    @pytest.mark.asyncio
    async def test_check_lockout_passes_when_lock_expired(self):
        past = datetime.now(UTC) - timedelta(seconds=1)
        user = _make_user(locked_until=past)
        await _check_lockout(user)  # Should not raise — lock has expired

    @pytest.mark.asyncio
    async def test_record_failure_increments_count(self):
        user = _make_user(fail_count=0)
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.login_fail_count == 1
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_failure_applies_lockout_at_threshold_1(self):
        user = _make_user(fail_count=LOCKOUT_THRESHOLD_1 - 1)
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.login_fail_count == LOCKOUT_THRESHOLD_1
        assert user.locked_until is not None

    @pytest.mark.asyncio
    async def test_record_failure_applies_extended_lockout_at_threshold_2(self):
        user = _make_user(fail_count=LOCKOUT_THRESHOLD_2 - 1)
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.login_fail_count == LOCKOUT_THRESHOLD_2
        assert user.locked_until is not None

    def test_lockout_threshold_1_less_than_threshold_2(self):
        # Sanity check on constants
        assert LOCKOUT_THRESHOLD_1 < LOCKOUT_THRESHOLD_2
