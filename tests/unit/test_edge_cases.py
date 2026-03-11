"""Additional edge case tests for RBAC, encryption, token blacklist, and lockout."""

import time

import pytest
from fastapi import HTTPException

from app.api.routers.auth import (
    LOCKOUT_THRESHOLD_1,
    LOCKOUT_THRESHOLD_2,
    _check_lockout,
    _lockout_lock,
    _login_failures,
    _record_failure,
    _reset_failures,
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
        assert not has_permission("operator", Permission.VIEW_AUDIT_LOG)

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
        secret = "my-secret-key-12345"
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
        with pytest.raises((ValueError, TypeError)):
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
def _clear_state():
    """Clear blacklist and lockout state."""
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    with _lockout_lock:
        _login_failures.clear()
    yield
    with _blacklist_lock:
        _blacklisted_tokens.clear()
        _user_token_blacklist.clear()
    with _lockout_lock:
        _login_failures.clear()


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


# --- Account Lockout Extended Tests ---


class TestAccountLockoutExtended:
    def test_progressive_lockout_5_attempts(self):
        ip = "172.16.0.1"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        with pytest.raises(HTTPException) as exc:
            _check_lockout(ip)
        assert exc.value.status_code == 429

    def test_progressive_lockout_10_attempts(self):
        ip = "172.16.0.2"
        for _ in range(LOCKOUT_THRESHOLD_2):
            _record_failure(ip)

        with pytest.raises(HTTPException) as exc:
            _check_lockout(ip)
        assert exc.value.status_code == 429

    def test_unlock_after_timeout(self):
        ip = "172.16.0.3"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        # Set lockout to past
        with _lockout_lock:
            _login_failures[ip]["locked_until"] = time.time() - 1

        _check_lockout(ip)  # Should not raise

    def test_different_ips_independent(self):
        ip1 = "172.16.0.4"
        ip2 = "172.16.0.5"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip1)

        with pytest.raises(HTTPException):
            _check_lockout(ip1)

        _check_lockout(ip2)  # Different IP should be fine

    def test_reset_clears_all_failures(self):
        ip = "172.16.0.6"
        for _ in range(LOCKOUT_THRESHOLD_1):
            _record_failure(ip)

        _reset_failures(ip)
        _check_lockout(ip)  # Should not raise after reset
