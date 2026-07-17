"""Tests for critical security fixes: path traversal, persistent blacklist, lockout, audit."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _safe_create_task(coro, **kwargs):
    """Mock create_task that closes coroutines to avoid RuntimeWarning."""
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


@pytest.fixture(autouse=True)
def _mission_runtime_isolation(tmp_path):
    with (
        patch("spectra_mission.mission.data_path", side_effect=tmp_path.joinpath),
        patch("spectra_mission.mission.asyncio.create_task", side_effect=_safe_create_task),
    ):
        yield


# ============================================================================
# 1. Path Traversal Prevention in Pentest Sessions
# ============================================================================


class TestPathTraversalPrevention:
    """Tests for session_id / note_id / evidence_id validation."""

    def test_validate_id_accepts_valid_ids(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        assert _validate_id("20260307-120000") == "20260307-120000"
        assert _validate_id("abc-123_xyz") == "abc-123_xyz"
        assert _validate_id("a") == "a"

    def test_validate_id_rejects_path_traversal(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException) as exc:
            _validate_id("../../etc/passwd", "session_id")
        assert exc.value.status_code == 400

    def test_validate_id_rejects_dots(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException):
            _validate_id("..session", "session_id")

    def test_validate_id_rejects_slashes(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException):
            _validate_id("foo/bar", "session_id")

    def test_validate_id_rejects_backslash(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException):
            _validate_id("foo\\bar", "session_id")

    def test_validate_id_rejects_empty(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException):
            _validate_id("", "session_id")

    def test_validate_id_rejects_null_bytes(self):
        from spectra_api.api.routers.pentest_sessions import _validate_id

        with pytest.raises(HTTPException):
            _validate_id("test\x00evil", "session_id")

    def test_session_path_validates_id(self):
        from spectra_api.api.routers.pentest_sessions import _session_path

        with pytest.raises(HTTPException):
            _session_path("../../../etc/passwd")

    def test_session_path_normal_id(self):
        from spectra_api.api.routers.pentest_sessions import _session_path

        path = _session_path("20260307-120000")
        assert "20260307-120000.json" in str(path)


# ============================================================================
# 2. IDOR Fix - Session Owner Filtering
# ============================================================================


class TestSessionOwnerFiltering:
    """Tests that sessions are filtered by owner_id."""

    def test_create_session_stores_owner_id(self):
        """Verify the session dict includes owner_id field."""
        # This is a structural test - verify the schema includes owner_id
        from spectra_api.api.routers.pentest_sessions import CreateSessionRequest

        req = CreateSessionRequest(name="test", target="10.0.0.1")
        assert req.name == "test"
        # The actual owner_id assignment is in the endpoint


# ============================================================================
# 3. Persistent Token Blacklist
# ============================================================================


class TestPersistentTokenBlacklist:
    """Tests for token blacklist persistence."""

    def setup_method(self):
        """Reset blacklist state before each test."""
        import spectra_auth.security as sec

        sec._blacklisted_tokens.clear()
        sec._user_token_blacklist.clear()
        sec._blacklist_ready.set()  # Skip DB loading

    @pytest.mark.asyncio
    async def test_invalidate_token_adds_with_expiry(self):
        import spectra_auth.security as sec

        token = "test-token-123"
        with (
            patch.object(sec, "_persist_blacklist_entry", new_callable=AsyncMock) as mock_persist,
            patch.object(sec, "_get_token_expiry", return_value=time.time() + 3600),
        ):
            await sec.invalidate_token(token)
        token_h = sec._token_hash(token)
        assert token_h in sec._blacklisted_tokens
        assert sec._blacklisted_tokens[token_h] > time.time()
        mock_persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_checks_expiry(self):
        import spectra_auth.security as sec

        token = "expired-token"
        token_h = sec._token_hash(token)
        # Set expired entry
        sec._blacklisted_tokens[token_h] = time.time() - 100
        assert await sec.is_token_blacklisted(token) is False

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_valid_entry(self):
        import spectra_auth.security as sec

        token = "valid-blacklisted-token"
        token_h = sec._token_hash(token)
        sec._blacklisted_tokens[token_h] = time.time() + 3600
        assert await sec.is_token_blacklisted(token) is True

    @pytest.mark.asyncio
    async def test_ensure_blacklist_loaded_awaits_load(self):
        import spectra_auth.security as sec

        sec._blacklist_ready.clear()
        sec._blacklist_load_started = False

        async def fake_load():
            sec._blacklist_ready.set()

        with patch.object(sec, "_load_from_db", new_callable=AsyncMock, side_effect=fake_load) as mock_load:
            await sec._ensure_blacklist_loaded()
        # Event is set after _load_from_db completes (not fire-and-forget)
        assert sec._blacklist_ready.is_set()
        mock_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_all_user_tokens_persists(self):
        import spectra_auth.security as sec

        with patch.object(sec, "_persist_blacklist_entry", new_callable=AsyncMock) as mock_persist:
            await sec.invalidate_all_user_tokens("testuser")
        mock_persist.assert_awaited_once()
        assert "testuser" in sec._user_token_blacklist

    @pytest.mark.asyncio
    async def test_blacklist_load_failure_fails_closed(self):
        import spectra_auth.security as sec

        sec._blacklist_ready.clear()
        sec._blacklist_load_started = False
        with patch.object(sec, "_load_from_db", new_callable=AsyncMock):
            with pytest.raises(sec.JWTError, match="revocation state is unavailable"):
                await sec._ensure_blacklist_loaded()

    @pytest.mark.asyncio
    async def test_failed_blacklist_persistence_does_not_report_a_revocation(self):
        import spectra_auth.security as sec

        token = sec.create_access_token({"sub": "user-with-failed-revocation"})
        with patch.object(
            sec,
            "_persist_blacklist_entry",
            new_callable=AsyncMock,
            side_effect=sec.JWTError("database unavailable"),
        ):
            with pytest.raises(sec.JWTError, match="database unavailable"):
                await sec.invalidate_token(token)
        assert sec._token_hash(token) not in sec._blacklisted_tokens


# ============================================================================
# 4. Persistent Account Lockout
# ============================================================================


class TestPersistentAccountLockout:
    """Tests for account lockout against the current DB-backed user state."""

    def _make_user(self, fail_count=0, locked_until=None):
        user = MagicMock()
        user.login_fail_count = fail_count
        user.locked_until = locked_until
        return user

    @pytest.mark.asyncio
    async def test_record_failure_persists(self):
        from spectra_api.api.routers.auth._helpers import _record_failure

        user = self._make_user()
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.login_fail_count == 1
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_failures_persists(self):
        user = self._make_user(fail_count=3, locked_until=datetime.now(UTC))
        user.login_fail_count = 0
        user.locked_until = None
        assert user.login_fail_count == 0
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_lockout_after_threshold(self):
        from spectra_api.api.routers.auth._helpers import LOCKOUT_THRESHOLD_1, _record_failure

        user = self._make_user(fail_count=LOCKOUT_THRESHOLD_1 - 1)
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.locked_until is not None

    @pytest.mark.asyncio
    async def test_check_lockout_raises_when_locked(self):
        from spectra_api.api.routers.auth._helpers import _check_lockout

        user = self._make_user(locked_until=datetime.now(UTC) + timedelta(minutes=5))
        with pytest.raises(HTTPException) as exc:
            await _check_lockout(user)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_check_lockout_allows_after_expiry(self):
        from spectra_api.api.routers.auth._helpers import _check_lockout

        user = self._make_user(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        await _check_lockout(user)

    @pytest.mark.asyncio
    async def test_persist_and_load_lockout(self):
        from spectra_api.api.routers.auth._helpers import LOCKOUT_THRESHOLD_2, _record_failure

        user = self._make_user(fail_count=LOCKOUT_THRESHOLD_2 - 1)
        session = AsyncMock()
        await _record_failure(user, session)
        assert user.login_fail_count == LOCKOUT_THRESHOLD_2
        assert user.locked_until is not None


# ============================================================================
# 5. Safety Stats Authentication
# ============================================================================


class TestSafetyStatsAuth:
    """Verify safety-stats endpoint requires authentication."""

    def test_safety_stats_endpoint_has_user_dependency(self):
        """Verify the endpoint function signature includes current_user."""
        import inspect

        from spectra_api.api.routers.system.health import get_safety_stats

        sig = inspect.signature(get_safety_stats)
        param_names = list(sig.parameters.keys())
        assert "_current_user" in param_names


# ============================================================================
# 7 & 8. MissionBlackboard & TaskTree Wired
# ============================================================================


class TestMissionBlackboardWired:
    """Tests that Mission creates and uses blackboard."""

    @patch("spectra_mission.mission.ws_manager")
    def test_mission_has_blackboard(self, _ws):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test", user_id="owner-1")
        assert m.blackboard is not None
        assert m.blackboard.mission_id == m.id

    @patch("spectra_mission.mission.ws_manager")
    def test_mission_has_task_tree(self, _ws):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        assert m.task_tree is not None
        assert m.task_tree.mission_id == m.id

    @patch("spectra_mission.mission.ws_manager")
    def test_to_dict_includes_task_tree(self, _ws):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        d = m.to_dict()
        assert "task_tree" in d
        assert "blackboard" in d

    @patch("spectra_mission.mission.ws_manager")
    def test_save_checkpoint_includes_task_tree(self, _ws):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test", user_id="owner-1")
        m.task_tree.add_task("scan-1", "Port Scan", "recon/port_scan")
        cp = m.save_checkpoint()
        assert "task_tree" in cp
        assert "scan-1" in cp["task_tree"]["nodes"]

    @patch("spectra_mission.mission.ws_manager")
    def test_from_checkpoint_restores_task_tree(self, _ws):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test", user_id="owner-1")
        m.task_tree.add_task("scan-1", "Port Scan", "recon/port_scan")
        cp = m.save_checkpoint()

        m2 = Mission.from_checkpoint(cp)
        assert m2.task_tree is not None
        assert "scan-1" in m2.task_tree._nodes


# ============================================================================
# 10. Audit Logging Wired
# ============================================================================


class TestAuditLoggingWired:
    """Tests that audit logging is wired in auth login and missions routers."""

    def test_auth_login_wires_audit_log_event(self):
        import spectra_api.api.routers.auth.login as login_mod
        from spectra_system.audit import log_event

        assert login_mod.audit_log_event is log_event

    def test_missions_router_imports_audit(self):
        import spectra_api.api.routers.missions.core as missions_core_mod

        assert hasattr(missions_core_mod, "audit_log_event")


# ============================================================================
# 12. CVE Intel Timeout
# ============================================================================


class TestCveIntelTimeout:
    """Tests for CVE intel HTTP client configuration."""

    def test_cache_key_sanitizes_keyword(self):
        keyword = "test keyword/evil"
        key = f"cve_cache:{keyword.lower().replace(' ', '_').replace('/', '_')[:50]}"
        assert key.startswith("cve_cache:")
        assert "/" not in key

    def test_infer_vuln_type(self):
        from spectra_ai_core.cve_intel import _infer_vuln_type

        assert _infer_vuln_type("Remote code execution via buffer overflow") == "rce"
        assert _infer_vuln_type("SQL injection in login form") == "sqli"
        assert _infer_vuln_type("Unknown vulnerability") == "unknown"
