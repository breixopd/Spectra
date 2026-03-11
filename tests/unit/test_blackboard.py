"""Tests for MissionBlackboard."""

import pytest

from app.services.ai.blackboard import (
    MAX_ENTRIES,
    MissionBlackboard,
    _blackboards,
    get_blackboard,
    remove_blackboard,
)


@pytest.fixture(autouse=True)
def _clean_blackboards():
    """Ensure global registry is clean between tests."""
    _blackboards.clear()
    yield
    _blackboards.clear()


class TestMissionBlackboard:
    """Tests for MissionBlackboard read/write."""

    def test_write_and_read(self):
        bb = MissionBlackboard("m1")
        bb.write("recon", "open_ports", [80, 443])
        assert bb.read("open_ports") == [80, 443]

    def test_read_nonexistent_key_returns_none(self):
        bb = MissionBlackboard("m1")
        assert bb.read("missing") is None

    def test_read_all_returns_all_values(self):
        bb = MissionBlackboard("m1")
        bb.write("recon", "ports", [80])
        bb.write("exploit", "creds", {"user": "admin"})
        result = bb.read_all()
        assert result == {"ports": [80], "creds": {"user": "admin"}}

    def test_overwrite_existing_key(self):
        bb = MissionBlackboard("m1")
        bb.write("a", "key", "old")
        bb.write("b", "key", "new")
        assert bb.read("key") == "new"

    def test_history_tracking(self):
        bb = MissionBlackboard("m1")
        bb.write("recon", "ports", [80])
        bb.write("exploit", "creds", "admin")
        history = bb.get_history()
        assert len(history) == 2
        assert history[0]["key"] == "ports"
        assert history[0]["agent"] == "recon"
        assert history[1]["key"] == "creds"
        assert history[1]["agent"] == "exploit"

    def test_max_entries_eviction(self):
        bb = MissionBlackboard("m1")
        # Fill to capacity
        for i in range(MAX_ENTRIES):
            bb.write("agent", f"key_{i}", i)
        assert len(bb.read_all()) == MAX_ENTRIES
        assert bb.read("key_0") == 0  # oldest still present

        # Add one more - oldest should be evicted
        bb.write("agent", "key_new", "val")
        assert len(bb.read_all()) == MAX_ENTRIES
        assert bb.read("key_0") is None  # evicted
        assert bb.read("key_new") == "val"

    def test_get_context_empty(self):
        bb = MissionBlackboard("m1")
        assert bb.get_context_for_agent("recon") == ""

    def test_get_context_with_data(self):
        bb = MissionBlackboard("m1")
        bb.write("recon", "ports", [80])
        ctx = bb.get_context_for_agent("exploit")
        assert "ports" in ctx
        assert "[80]" in ctx
        assert "recon" in ctx


class TestBlackboardRegistry:
    """Tests for module-level get/remove."""

    def test_get_creates_new(self):
        bb = get_blackboard("mission-1")
        assert isinstance(bb, MissionBlackboard)
        assert bb.mission_id == "mission-1"

    def test_get_returns_same_instance(self):
        bb1 = get_blackboard("mission-1")
        bb2 = get_blackboard("mission-1")
        assert bb1 is bb2

    def test_remove_cleans_up(self):
        bb = get_blackboard("mission-1")
        bb.write("a", "key", "val")
        remove_blackboard("mission-1")
        # New call should give fresh instance
        bb2 = get_blackboard("mission-1")
        assert bb2.read("key") is None

    def test_remove_nonexistent_is_noop(self):
        remove_blackboard("does-not-exist")  # should not raise
