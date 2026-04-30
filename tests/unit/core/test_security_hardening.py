"""Tests for security hardening and session migration features."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _safe_create_task(coro, **kwargs):
    """Mock create_task that closes coroutines to avoid RuntimeWarning."""
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


@pytest.fixture(autouse=True)
def _mission_runtime_isolation(tmp_path):
    with (
        patch("app.services.mission.mission.data_path", side_effect=tmp_path.joinpath),
        patch("app.services.mission.mission.asyncio.create_task", side_effect=_safe_create_task),
    ):
        yield


from app.auth.encryption import (
    _derive_fernet_key,
    decrypt_field,
    decrypt_sensitive_fields,
    encrypt_field,
    encrypt_sensitive_fields,
    is_sensitive_key,
)
from app.models.user import User
from app.services.ai.agents.post_exploitation import (
    POST_EXPLOIT_TOOLS,
    PostExploitAction,
    PostExploitationAgent,
    PostExploitInput,
    _detect_os,
)
from app.services.mission.mission import Mission
from spectra_api.authz import ROLE_PERMISSIONS, Permission, has_permission, require_permission

# ============================================================================
# SEC-001: RBAC Tests
# ============================================================================


class TestRBACPermissions:
    """Tests for the RBAC permission system."""

    def test_admin_has_all_permissions(self):
        for perm in Permission:
            assert has_permission("admin", perm), f"Admin missing {perm}"

    def test_user_has_operational_perms(self):
        assert has_permission("user", Permission.VIEW_MISSIONS)
        assert has_permission("user", Permission.CREATE_MISSIONS)
        assert has_permission("user", Permission.MANAGE_MISSIONS)
        assert has_permission("user", Permission.VIEW_FINDINGS)
        assert has_permission("user", Permission.MANAGE_FINDINGS)
        assert has_permission("user", Permission.USE_TOOLS)
        assert has_permission("user", Permission.VIEW_REPORTS)

    def test_user_lacks_admin_perms(self):
        assert not has_permission("user", Permission.MANAGE_SETTINGS)
        assert not has_permission("user", Permission.MANAGE_USERS)
        assert not has_permission("user", Permission.VIEW_AUDIT_LOG)

    def test_staff_has_read_and_support_perms(self):
        assert has_permission("staff", Permission.VIEW_MISSIONS)
        assert has_permission("staff", Permission.VIEW_FINDINGS)
        assert has_permission("staff", Permission.VIEW_TARGETS)
        assert has_permission("staff", Permission.VIEW_REPORTS)
        assert has_permission("staff", Permission.MANAGE_USERS)
        assert has_permission("staff", Permission.VIEW_AUDIT_LOG)
        assert has_permission("staff", Permission.VIEW_MONITORING)

    def test_staff_lacks_write_perms(self):
        assert not has_permission("staff", Permission.CREATE_MISSIONS)
        assert not has_permission("staff", Permission.MANAGE_MISSIONS)
        assert not has_permission("staff", Permission.MANAGE_FINDINGS)
        assert not has_permission("staff", Permission.USE_TOOLS)
        assert not has_permission("staff", Permission.MANAGE_SETTINGS)

    def test_unknown_role_has_no_permissions(self):
        for perm in Permission:
            assert not has_permission("unknown_role", perm)

    def test_all_permissions_accounted_for(self):
        """Every Permission enum member should appear in at least admin."""
        admin_perms = ROLE_PERMISSIONS["admin"]
        assert admin_perms == set(Permission)

    def test_role_permissions_are_sets(self):
        for role, perms in ROLE_PERMISSIONS.items():
            assert isinstance(perms, set), f"{role} perms not a set"


class TestRBACDependency:
    """Tests for the require_permission FastAPI dependency."""

    def test_require_permission_returns_depends(self):
        dep = require_permission(Permission.MANAGE_SETTINGS)
        # FastAPI Depends objects have a dependency attribute
        assert dep is not None


class TestUserRoleField:
    """Tests for the User model role field."""

    def test_user_model_has_role_column(self):
        columns = {c.name for c in User.__table__.columns}
        assert "role" in columns

    def test_role_column_default(self):
        col = User.__table__.columns["role"]
        assert col.server_default is not None


# ============================================================================
# SEC-007: Encryption Tests
# ============================================================================


class TestFieldEncryption:
    """Tests for field-level encryption."""

    def test_encrypt_decrypt_roundtrip(self):
        secret = "test-secret-key-12345"
        plaintext = "my_super_secret_password"
        encrypted = encrypt_field(plaintext, secret)
        decrypted = decrypt_field(encrypted, secret)
        assert decrypted == plaintext

    def test_encrypted_differs_from_plaintext(self):
        secret = "test-secret"
        plaintext = "password123"
        encrypted = encrypt_field(plaintext, secret)
        assert encrypted != plaintext

    def test_wrong_key_fails(self):
        from cryptography.fernet import InvalidToken

        encrypted = encrypt_field("secret", "key1")
        with pytest.raises(InvalidToken):
            decrypt_field(encrypted, "wrong_key")

    def test_derive_key_deterministic(self):
        key1 = _derive_fernet_key("same_secret")
        key2 = _derive_fernet_key("same_secret")
        assert key1 == key2

    def test_derive_key_different_secrets(self):
        key1 = _derive_fernet_key("secret_a")
        key2 = _derive_fernet_key("secret_b")
        assert key1 != key2


class TestSensitiveKeyDetection:
    """Tests for sensitive key detection."""

    def test_password_detected(self):
        assert is_sensitive_key("password")
        assert is_sensitive_key("user_password")
        assert is_sensitive_key("db_Password")

    def test_secret_detected(self):
        assert is_sensitive_key("secret")
        assert is_sensitive_key("client_secret")

    def test_token_detected(self):
        assert is_sensitive_key("access_token")
        assert is_sensitive_key("refresh_token")

    def test_credential_detected(self):
        assert is_sensitive_key("credential")
        assert is_sensitive_key("aws_credentials")

    def test_api_key_detected(self):
        assert is_sensitive_key("api_key")
        assert is_sensitive_key("openai_api_key")

    def test_non_sensitive_not_detected(self):
        assert not is_sensitive_key("username")
        assert not is_sensitive_key("host")
        assert not is_sensitive_key("port")
        assert not is_sensitive_key("name")


class TestBulkEncryption:
    """Tests for encrypting/decrypting dict fields."""

    def test_encrypt_sensitive_fields(self):
        secret = "test-key"
        data = {
            "name": "Test Session",
            "password": "secret123",
            "host": "10.0.0.1",
            "api_token": "tok_abc",
        }
        encrypted = encrypt_sensitive_fields(data, secret)
        assert encrypted["name"] == "Test Session"
        assert encrypted["host"] == "10.0.0.1"
        assert encrypted["password"] != "secret123"
        assert encrypted["api_token"] != "tok_abc"

    def test_decrypt_sensitive_fields(self):
        secret = "test-key"
        data = {"password": "secret123", "name": "hi"}
        encrypted = encrypt_sensitive_fields(data, secret)
        decrypted = decrypt_sensitive_fields(encrypted, secret)
        assert decrypted["password"] == "secret123"
        assert decrypted["name"] == "hi"

    def test_roundtrip_preserves_all(self):
        secret = "key"
        data = {
            "id": "123",
            "password": "pw",
            "secret_data": "hidden",
            "status": "active",
        }
        result = decrypt_sensitive_fields(encrypt_sensitive_fields(data, secret), secret)
        assert result == data

    def test_nested_dict_encryption(self):
        secret = "key"
        data = {
            "host": "localhost",
            "creds": {"password": "pw123", "user": "admin"},
        }
        encrypted = encrypt_sensitive_fields(data, secret)
        assert encrypted["creds"]["password"] != "pw123"
        assert encrypted["creds"]["user"] == "admin"

        decrypted = decrypt_sensitive_fields(encrypted, secret)
        assert decrypted["creds"]["password"] == "pw123"

    def test_already_encrypted_skipped(self):
        secret = "key"
        data = {"password": "gAAAAA_already_encrypted_token"}
        encrypted = encrypt_sensitive_fields(data, secret)
        # Should not double-encrypt
        assert encrypted["password"] == "gAAAAA_already_encrypted_token"

    def test_empty_values_skipped(self):
        secret = "key"
        data = {"password": "", "token": None, "name": "test"}
        encrypted = encrypt_sensitive_fields(data, secret)
        assert encrypted["password"] == ""
        assert encrypted["token"] is None


# ============================================================================
# AGENT-004: PostExploitation Tool Queue
# ============================================================================


class TestPostExploitTools:
    """Tests for post-exploitation tool auto-queuing."""

    def test_linux_tools_defined(self):
        assert "linux" in POST_EXPLOIT_TOOLS
        tools = POST_EXPLOIT_TOOLS["linux"]
        assert len(tools) >= 2
        assert any(t.get("tool") == "linpeas" for t in tools)

    def test_windows_tools_defined(self):
        assert "windows" in POST_EXPLOIT_TOOLS
        tools = POST_EXPLOIT_TOOLS["windows"]
        assert len(tools) >= 2
        assert any(t.get("tool") == "winpeas" for t in tools)

    def test_detect_os_linux(self):
        assert _detect_os("Ubuntu 22.04 LTS", "user") == "linux"
        assert _detect_os(None, "root") == "linux"
        assert _detect_os("", "user") == "linux"

    def test_detect_os_windows(self):
        assert _detect_os("Windows Server 2019", "admin") == "windows"
        assert _detect_os("Microsoft Windows 10", "user") == "windows"

    def test_action_has_tool_queue_field(self):
        action = PostExploitAction(
            action_type="post_exploit_plan",
            confidence=0.8,
            reasoning="test",
            suggested_actions=["enum"],
            tool_queue=[{"tool": "linpeas", "purpose": "privesc"}],
        )
        assert len(action.tool_queue) == 1


class TestPostExploitAgent:
    """Tests for the PostExploitationAgent execution."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.generate_structured = AsyncMock(
            return_value=PostExploitAction(
                action_type="post_exploit_plan",
                confidence=0.8,
                reasoning="Post-exploitation plan",
                suggested_actions=["check sudo"],
                persistence_methods=["cron"],
                exfiltration_targets=["/etc/shadow"],
            )
        )
        return llm

    @pytest.mark.asyncio
    async def test_execute_queues_linux_tools(self, mock_llm):
        from app.services.ai.agents.base import AgentContext

        agent = PostExploitationAgent(mock_llm)
        ctx = AgentContext(mission_id="test-1", target="10.0.0.1")
        inp = PostExploitInput(target="10.0.0.1", access_level="user", system_info="Ubuntu 22.04")

        result = await agent.execute(ctx, inp)
        assert result.success
        assert result.metadata["detected_os"] == "linux"
        assert result.action.tool_queue == POST_EXPLOIT_TOOLS["linux"]

    @pytest.mark.asyncio
    async def test_execute_queues_windows_tools(self, mock_llm):
        from app.services.ai.agents.base import AgentContext

        agent = PostExploitationAgent(mock_llm)
        ctx = AgentContext(mission_id="test-1", target="10.0.0.1")
        inp = PostExploitInput(target="10.0.0.1", access_level="admin", system_info="Windows Server 2019")

        result = await agent.execute(ctx, inp)
        assert result.success
        assert result.metadata["detected_os"] == "windows"
        assert result.action.tool_queue == POST_EXPLOIT_TOOLS["windows"]


# ============================================================================
# MISSION-003: Enhanced Isolation
# ============================================================================


class TestMissionIsolation:
    """Tests for mission-scoped logging and output directories."""

    def test_mission_has_scoped_logger(self):
        mission = Mission("10.0.0.1", "test")
        assert mission._logger.name.startswith("spectra.mission.")
        assert mission.id[:8] in mission._logger.name

    def test_mission_has_output_dir(self):
        mission = Mission("10.0.0.1", "test")
        assert mission.id in str(mission.output_dir)
        assert mission.output_dir.name == mission.id

    def test_log_includes_mission_id_prefix(self):
        mission = Mission("10.0.0.1", "test")
        mission.log("Test message")
        assert any(mission.id[:8] in entry for entry in mission.logs)

    def test_different_missions_different_loggers(self):
        m1 = Mission("10.0.0.1", "test1")
        m2 = Mission("10.0.0.2", "test2")
        assert m1._logger.name != m2._logger.name

    def test_different_missions_different_output_dirs(self):
        m1 = Mission("10.0.0.1", "test1")
        m2 = Mission("10.0.0.2", "test2")
        assert m1.output_dir != m2.output_dir


# ============================================================================
# MISSION-004: Enhanced Finding Dedup
# ============================================================================


class TestEnhancedFindingDedup:
    """Tests for protocol stripping, port normalization, CVE grouping."""

    def test_protocol_stripped_for_dedup(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS", "host": "http://target.com", "port": 80})
        mission.add_finding({"name": "XSS", "host": "https://target.com", "port": 80})
        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2

    def test_port_80_443_normalized(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 80})
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 443})
        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2

    def test_trailing_slash_normalized(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS", "host": "target.com/", "port": 8080})
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 8080})
        assert len(mission.findings) == 1

    def test_related_cves_deduped(self):
        mission = Mission("target.com", "test")
        mission.add_finding(
            {
                "name": "Apache Path Traversal",
                "host": "target.com",
                "port": 80,
                "cve_id": "CVE-2021-41773",
            }
        )
        mission.add_finding(
            {
                "name": "Apache Path Traversal",
                "host": "target.com",
                "port": 80,
                "cve_id": "CVE-2021-42013",
            }
        )
        # These are related CVEs (same host/port) — should fuzzy-dedup
        assert len(mission.findings) == 1

    def test_unrelated_cves_not_deduped(self):
        mission = Mission("target.com", "test")
        mission.add_finding(
            {
                "name": "SQL Injection in login form via user parameter",
                "host": "target.com",
                "port": 8080,
                "cve_id": "CVE-2020-1234",
            }
        )
        mission.add_finding(
            {
                "name": "Remote Code Execution via deserialization flaw",
                "host": "target.com",
                "port": 8080,
                "cve_id": "CVE-2022-5678",
            }
        )
        assert len(mission.findings) == 2

    def test_are_related_cves_class_method(self):
        assert Mission._are_related_cves("CVE-2021-41773", "CVE-2021-42013")
        assert Mission._are_related_cves("CVE-2021-44228", "CVE-2021-45046")
        assert not Mission._are_related_cves("CVE-2021-44228", "CVE-2020-1234")
        assert not Mission._are_related_cves(None, "CVE-2020-1234")
        assert not Mission._are_related_cves("", "")


# ============================================================================
# PentestSession Model Tests
# ============================================================================


class TestPentestSessionModel:
    """Tests for the PentestSession DB model."""

    def test_model_has_required_columns(self):
        from app.models.pentest_session import PentestSession

        columns = {c.name for c in PentestSession.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "name" in columns
        assert "target" in columns
        assert "status" in columns
        assert "session_data" in columns
        assert "created_at" in columns
        assert "updated_at" in columns

    def test_model_tablename(self):
        from app.models.pentest_session import PentestSession

        assert PentestSession.__tablename__ == "pentest_sessions"

    def test_model_in_models_package(self):
        from app.models import PentestSession

        assert PentestSession is not None
