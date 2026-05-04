"""Tests for MissionBlackboard."""

import asyncio
import inspect

import pytest

from spectra_platform.services.ai.blackboard import (
    MAX_ENTRIES,
    MAX_HISTORY,
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


class TestBlackboardRealScenarios:
    """Tests for real-world usage patterns."""

    def test_store_complex_tool_results(self):
        bb = MissionBlackboard("m1")
        tool_result = {
            "tool": "nmap",
            "ports": [22, 80, 443],
            "services": {"22": "ssh", "80": "http", "443": "https"},
            "os_guess": "Linux 5.x",
        }
        bb.write("parser", "nmap_results", tool_result)
        assert bb.read("nmap_results") == tool_result
        nmap_result = bb.read("nmap_results")
        assert nmap_result is not None
        assert nmap_result["ports"] == [22, 80, 443]

    def test_store_scope_definitions(self):
        bb = MissionBlackboard("m1")
        scope = {
            "targets": ["192.168.1.0/24"],
            "excluded": ["192.168.1.1"],
            "ports": "1-65535",
            "stealth": True,
        }
        bb.write("scope", "mission_scope", scope)
        scope_result = bb.read("mission_scope")
        assert scope_result is not None
        assert scope_result["targets"] == ["192.168.1.0/24"]
        assert scope_result["stealth"] is True

    def test_history_properly_maintained(self):
        bb = MissionBlackboard("m1")
        bb.write("recon", "ports", [80])
        bb.write("exploit", "creds", "admin")
        bb.write("recon", "ports", [80, 443])  # overwrite
        history = bb.get_history()
        assert len(history) == 3
        assert history[0]["action"] == "write"
        assert history[2]["key"] == "ports"
        assert history[2]["agent"] == "recon"

    def test_eviction_oldest_first(self):
        bb = MissionBlackboard("m1")
        for i in range(MAX_ENTRIES):
            bb.write("agent", f"k{i}", i)
        # Oldest key is k0
        assert bb.read("k0") == 0
        # Add one more → k0 evicted
        bb.write("agent", "new_key", "new")
        assert bb.read("k0") is None
        assert bb.read("k1") == 1  # second oldest survives
        assert bb.read("new_key") == "new"

    def test_history_truncation(self):
        bb = MissionBlackboard("m1")
        for i in range(MAX_HISTORY + 100):
            bb.write("agent", f"k{i % 50}", i)
        assert len(bb.get_history()) == MAX_HISTORY

    @pytest.mark.asyncio
    async def test_concurrent_writes(self):
        bb = MissionBlackboard("m1")

        async def writer(agent: str, n: int):
            for i in range(n):
                bb.write(agent, f"{agent}_{i}", i)
                await asyncio.sleep(0)

        await asyncio.gather(
            writer("recon", 50),
            writer("exploit", 50),
            writer("parser", 50),
        )
        # All 150 unique keys should be present (well under MAX_ENTRIES)
        assert len(bb.read_all()) == 150

    @pytest.mark.asyncio
    async def test_concurrent_read_write(self):
        bb = MissionBlackboard("m1")
        bb.write("init", "shared", 0)

        async def reader():
            for _ in range(100):
                bb.read("shared")
                await asyncio.sleep(0)

        async def writer():
            for i in range(100):
                bb.write("w", "shared", i)
                await asyncio.sleep(0)

        await asyncio.gather(reader(), writer())
        # Should end with last written value
        assert bb.read("shared") == 99


def test_get_cross_mission_findings_requires_user_id():
    sig = inspect.signature(MissionBlackboard.get_cross_mission_findings)
    assert "user_id" in sig.parameters
    assert sig.parameters["user_id"].default is inspect.Parameter.empty
