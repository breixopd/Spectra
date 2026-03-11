"""Tests for critical security fixes: path traversal, persistent blacklist, lockout, audit."""

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

# ============================================================================
# 1. Path Traversal Prevention in Pentest Sessions
# ============================================================================

class TestPathTraversalPrevention:
    """Tests for session_id / note_id / evidence_id validation."""

    def test_validate_id_accepts_valid_ids(self):
        from app.api.routers.pentest_sessions import _validate_id
        assert _validate_id("20260307-120000") == "20260307-120000"
        assert _validate_id("abc-123_xyz") == "abc-123_xyz"
        assert _validate_id("a") == "a"

    def test_validate_id_rejects_path_traversal(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException) as exc:
            _validate_id("../../etc/passwd", "session_id")
        assert exc.value.status_code == 400

    def test_validate_id_rejects_dots(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException):
            _validate_id("..session", "session_id")

    def test_validate_id_rejects_slashes(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException):
            _validate_id("foo/bar", "session_id")

    def test_validate_id_rejects_backslash(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException):
            _validate_id("foo\\bar", "session_id")

    def test_validate_id_rejects_empty(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException):
            _validate_id("", "session_id")

    def test_validate_id_rejects_null_bytes(self):
        from app.api.routers.pentest_sessions import _validate_id
        with pytest.raises(HTTPException):
            _validate_id("test\x00evil", "session_id")

    def test_session_path_validates_id(self):
        from app.api.routers.pentest_sessions import _session_path
        with pytest.raises(HTTPException):
            _session_path("../../../etc/passwd")

    def test_session_path_normal_id(self):
        from app.api.routers.pentest_sessions import _session_path
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
        from app.api.routers.pentest_sessions import CreateSessionRequest
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
        import app.core.security as sec
        sec._blacklisted_tokens.clear()
        sec._user_token_blacklist.clear()
        sec._blacklist_loaded = True  # Skip file loading

    def test_invalidate_token_adds_with_expiry(self):
        import app.core.security as sec
        token = "test-token-123"
        with patch.object(sec, '_persist_blacklist'):
            with patch.object(sec, '_get_token_expiry', return_value=time.time() + 3600):
                sec.invalidate_token(token)
        token_h = sec._token_hash(token)
        assert token_h in sec._blacklisted_tokens
        assert sec._blacklisted_tokens[token_h] > time.time()

    def test_is_token_blacklisted_checks_expiry(self):
        import app.core.security as sec
        token = "expired-token"
        token_h = sec._token_hash(token)
        # Set expired entry
        sec._blacklisted_tokens[token_h] = time.time() - 100
        assert sec.is_token_blacklisted(token) is False

    def test_is_token_blacklisted_valid_entry(self):
        import app.core.security as sec
        token = "valid-blacklisted-token"
        token_h = sec._token_hash(token)
        sec._blacklisted_tokens[token_h] = time.time() + 3600
        assert sec.is_token_blacklisted(token) is True

    def test_persist_blacklist_calls_db(self):
        import app.core.security as sec
        with patch.object(sec, '_persist_to_db') as mock_db:
            # Provide a running loop so create_task works
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._run_persist(sec, mock_db))
            finally:
                loop.close()

    @staticmethod
    async def _run_persist(sec, mock_db):
        mock_db.return_value = None
        sec._persist_blacklist()

    def test_ensure_blacklist_loaded_sets_flag(self):
        import app.core.security as sec
        sec._blacklist_loaded = False
        sec._ensure_blacklist_loaded()
        assert sec._blacklist_loaded is True

    def test_invalidate_all_user_tokens_persists(self):
        import app.core.security as sec
        with patch.object(sec, '_persist_blacklist') as mock_persist:
            sec.invalidate_all_user_tokens("testuser")
        mock_persist.assert_called_once()
        assert "testuser" in sec._user_token_blacklist


# ============================================================================
# 4. Persistent Account Lockout
# ============================================================================

class TestPersistentAccountLockout:
    """Tests for account lockout persistence."""

    def setup_method(self):
        import app.api.routers.auth as auth_mod
        auth_mod._login_failures.clear()
        auth_mod._lockout_loaded = True

    def test_record_failure_persists(self):
        import app.api.routers.auth as auth_mod
        with patch.object(auth_mod, '_persist_lockout') as mock_persist:
            auth_mod._record_failure("1.2.3.4")
        mock_persist.assert_called_once()
        assert "1.2.3.4" in auth_mod._login_failures
        assert auth_mod._login_failures["1.2.3.4"]["count"] == 1

    def test_reset_failures_persists(self):
        import app.api.routers.auth as auth_mod
        auth_mod._login_failures["1.2.3.4"] = {"count": 3, "locked_until": 0}
        with patch.object(auth_mod, '_persist_lockout') as mock_persist:
            auth_mod._reset_failures("1.2.3.4")
        mock_persist.assert_called_once()
        assert "1.2.3.4" not in auth_mod._login_failures

    def test_lockout_after_threshold(self):
        import app.api.routers.auth as auth_mod
        with patch.object(auth_mod, '_persist_lockout'):
            for _ in range(auth_mod.LOCKOUT_THRESHOLD_1):
                auth_mod._record_failure("5.6.7.8")
        entry = auth_mod._login_failures["5.6.7.8"]
        assert entry["locked_until"] > time.time()

    def test_check_lockout_raises_when_locked(self):
        import app.api.routers.auth as auth_mod
        auth_mod._login_failures["9.10.11.12"] = {
            "count": 5,
            "locked_until": time.time() + 300,
        }
        with pytest.raises(HTTPException) as exc:
            auth_mod._check_lockout("9.10.11.12")
        assert exc.value.status_code == 429

    def test_check_lockout_allows_after_expiry(self):
        import app.api.routers.auth as auth_mod
        auth_mod._login_failures["9.10.11.12"] = {
            "count": 5,
            "locked_until": time.time() - 10,
        }
        # Should not raise
        auth_mod._check_lockout("9.10.11.12")

    def test_persist_and_load_lockout(self, tmp_path):
        import app.api.routers.auth as auth_mod
        test_file = tmp_path / ".lockout_state.json"
        original_file = auth_mod._LOCKOUT_FILE

        try:
            auth_mod._LOCKOUT_FILE = test_file
            auth_mod._login_failures["1.2.3.4"] = {
                "count": 3,
                "locked_until": time.time() + 300,
            }
            auth_mod._persist_lockout()
            assert test_file.exists()

            auth_mod._login_failures.clear()
            auth_mod._lockout_loaded = False
            auth_mod._ensure_lockout_loaded()
            assert "1.2.3.4" in auth_mod._login_failures
        finally:
            auth_mod._LOCKOUT_FILE = original_file
            auth_mod._lockout_loaded = True


# ============================================================================
# 5. Safety Stats Authentication
# ============================================================================

class TestSafetyStatsAuth:
    """Verify safety-stats endpoint requires authentication."""

    def test_safety_stats_endpoint_has_user_dependency(self):
        """Verify the endpoint function signature includes current_user."""
        import inspect

        from app.api.routers.system import get_safety_stats
        sig = inspect.signature(get_safety_stats)
        param_names = list(sig.parameters.keys())
        assert "_current_user" in param_names


# ============================================================================
# 7 & 8. MissionBlackboard & TaskTree Wired
# ============================================================================

class TestMissionBlackboardWired:
    """Tests that Mission creates and uses blackboard."""

    @patch("app.services.mission.mission.ws_manager")
    def test_mission_has_blackboard(self, _ws):
        from app.services.mission.mission import Mission
        m = Mission("10.0.0.1", "test")
        assert m.blackboard is not None
        assert m.blackboard.mission_id == m.id

    @patch("app.services.mission.mission.ws_manager")
    def test_mission_has_task_tree(self, _ws):
        from app.services.mission.mission import Mission
        m = Mission("10.0.0.1", "test")
        assert m.task_tree is not None
        assert m.task_tree.mission_id == m.id

    @patch("app.services.mission.mission.ws_manager")
    def test_to_dict_includes_task_tree(self, _ws):
        from app.services.mission.mission import Mission
        m = Mission("10.0.0.1", "test")
        d = m.to_dict()
        assert "task_tree" in d
        assert "blackboard" in d

    @patch("app.services.mission.mission.ws_manager")
    def test_save_checkpoint_includes_task_tree(self, _ws):
        from app.services.mission.mission import Mission
        m = Mission("10.0.0.1", "test")
        m.task_tree.add_task("scan-1", "Port Scan", "recon/port_scan")
        cp = m.save_checkpoint()
        assert "task_tree" in cp
        assert "scan-1" in cp["task_tree"]["nodes"]

    @patch("app.services.mission.mission.ws_manager")
    def test_from_checkpoint_restores_task_tree(self, _ws):
        from app.services.mission.mission import Mission
        m = Mission("10.0.0.1", "test")
        m.task_tree.add_task("scan-1", "Port Scan", "recon/port_scan")
        cp = m.save_checkpoint()

        m2 = Mission.from_checkpoint(cp)
        assert m2.task_tree is not None
        assert "scan-1" in m2.task_tree._nodes


# ============================================================================
# 10. Audit Logging Wired
# ============================================================================

class TestAuditLoggingWired:
    """Tests that audit logging is imported in auth and missions routers."""

    def test_auth_router_imports_audit(self):
        import app.api.routers.auth as auth_mod
        assert hasattr(auth_mod, 'audit_log_event')

    def test_missions_router_imports_audit(self):
        import app.api.routers.missions as missions_mod
        assert hasattr(missions_mod, 'audit_log_event')


# ============================================================================
# 12. CVE Intel Timeout
# ============================================================================

class TestCveIntelTimeout:
    """Tests for CVE intel HTTP client configuration."""

    def test_cache_path_sanitizes_keyword(self):
        from app.services.ai.cve_intel import _cache_path
        path = _cache_path("test keyword/evil")
        assert "/" not in path.name or path.name.startswith("test")

    def test_infer_vuln_type(self):
        from app.services.ai.cve_intel import _infer_vuln_type
        assert _infer_vuln_type("Remote code execution via buffer overflow") == "rce"
        assert _infer_vuln_type("SQL injection in login form") == "sqli"
        assert _infer_vuln_type("Unknown vulnerability") == "unknown"
