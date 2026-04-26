"""Tests for new features: checkpoint/resume, replanning, steering, caching, stealth, dedup."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.constants import MAX_CONCURRENT_MISSIONS, MAX_REPLANS_PER_MISSION
from app.core.optimizations import ToolResultCache
from app.services.mission.mission import Mission


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


# --- MISSION-002: Checkpoint/Resume ---


class TestMissionCheckpoint:
    """Tests for mission checkpoint and resume."""

    def test_save_checkpoint_returns_serializable(self):
        mission = Mission("192.168.1.1", "Full scan")
        mission.add_finding({"name": "XSS", "host": "192.168.1.1", "port": 80})
        mission.record_tool_run("nmap")
        mission.record_tool_run("nuclei")

        checkpoint = mission.save_checkpoint()

        assert checkpoint["id"] == mission.id
        assert checkpoint["target"] == "192.168.1.1"
        assert checkpoint["directive"] == "Full scan"
        assert len(checkpoint["findings"]) == 1
        assert "nmap" in checkpoint["tools_run"]
        assert "nuclei" in checkpoint["tools_run"]
        assert checkpoint["current_task_index"] == 0
        assert checkpoint["replan_count"] == 0

    def test_from_checkpoint_reconstructs_mission(self):
        mission = Mission("10.0.0.1", "Network assessment")
        mission.status = "running"
        mission.current_task_index = 3
        mission.add_finding({"name": "Open port", "host": "10.0.0.1", "port": 22})
        mission.record_tool_run("nmap")
        mission.skipped_phases.add("exploitation")
        mission.replan_count = 2

        checkpoint = mission.save_checkpoint()
        restored = Mission.from_checkpoint(checkpoint)

        assert restored.id == mission.id
        assert restored.target == "10.0.0.1"
        assert restored.directive == "Network assessment"
        assert restored.current_task_index == 3
        assert len(restored.findings) == 1
        assert "nmap" in restored.tools_run
        assert "exploitation" in restored.skipped_phases
        assert restored.replan_count == 2

    def test_checkpoint_with_empty_mission(self):
        mission = Mission("example.com", "Recon")
        checkpoint = mission.save_checkpoint()
        restored = Mission.from_checkpoint(checkpoint)

        assert restored.id == mission.id
        assert restored.findings == []
        assert restored.tools_run == []


# --- MISSION-003: Concurrent Mission Isolation ---


class TestConcurrentMissionIsolation:
    """Tests for concurrent mission isolation constants."""

    def test_max_concurrent_missions_default(self):
        assert MAX_CONCURRENT_MISSIONS == 10

    @pytest.mark.asyncio
    async def test_mission_manager_has_global_semaphore(self):
        from app.services.mission.manager import MissionManager

        with patch("app.core.database.async_session_maker"):
            manager = MissionManager()
            assert isinstance(manager._global_semaphore, asyncio.Semaphore)


# --- MISSION-004: Better Finding Deduplication ---


class TestFindingDeduplication:
    """Tests for improved finding deduplication."""

    def test_exact_duplicate_increments_count(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 80})
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 80})

        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2

    def test_case_insensitive_dedup(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "SQL Injection", "host": "target.com", "port": 80})
        mission.add_finding({"name": "sql injection", "host": "target.com", "port": 80})

        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2

    def test_different_findings_not_deduped(self):
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS", "host": "target.com", "port": 80})
        mission.add_finding({"name": "SQLi", "host": "target.com", "port": 3306})

        assert len(mission.findings) == 2

    def test_fuzzy_duplicate_same_host_port_similar_desc(self):
        mission = Mission("target.com", "test")
        mission.add_finding(
            {
                "name": "short",
                "description": "SQL injection in login parameter",
                "host": "target.com",
                "port": 80,
            }
        )
        mission.add_finding(
            {
                "name": "short",
                "description": "SQL injection in login parameter found",
                "host": "target.com",
                "port": 80,
            }
        )

        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2

    def test_dedup_preserves_original_case_in_name(self):
        """The stored finding should keep its original casing."""
        mission = Mission("target.com", "test")
        mission.add_finding({"name": "XSS Vulnerability", "host": "target.com"})

        assert mission.findings[0]["name"] == "XSS Vulnerability"

    def test_normalize_finding_returns_copy(self):
        original = {"name": "  XSS  ", "host": "  Target.COM  "}
        normalized = Mission._normalize_finding(original)

        assert normalized["name"] == "xss"
        assert normalized["host"] == "target.com"
        # Original unchanged
        assert original["name"] == "  XSS  "


# --- MISSION-006: Dynamic Replanning ---


class TestDynamicReplanning:
    """Tests for dynamic replanning capability."""

    def test_replan_inserts_tasks(self):
        mission = Mission("target.com", "test")
        # Need a plan with tasks
        plan = MagicMock()
        plan.tasks = [MagicMock(description="Task 1"), MagicMock(description="Task 2")]
        mission.plan = plan
        mission.current_task_index = 0

        new_task = MagicMock(description="Extra enum")
        result = mission.replan("Exploit failed", [new_task])

        assert result is True
        assert mission.replan_count == 1
        assert len(mission.plan.tasks) == 3
        assert mission.plan.tasks[1] == new_task

    def test_replan_limited_to_max(self):
        mission = Mission("target.com", "test")
        plan = MagicMock()
        plan.tasks = [MagicMock()]
        mission.plan = plan

        for i in range(MAX_REPLANS_PER_MISSION):
            assert mission.replan(f"Reason {i}", [MagicMock()]) is True

        assert mission.replan("One too many", [MagicMock()]) is False
        assert mission.replan_count == MAX_REPLANS_PER_MISSION

    def test_replan_without_plan_returns_false(self):
        mission = Mission("target.com", "test")
        assert mission.replan("No plan", [MagicMock()]) is False

    def test_max_replans_constant(self):
        assert MAX_REPLANS_PER_MISSION == 3


# --- MISSION-007: Extended Steering Actions ---


class TestExtendedSteeringActions:
    """Tests for new steering actions."""

    @pytest.fixture
    def steering_manager(self):
        from app.services.mission.manager.steering import MissionSteeringManager

        missions = {}
        return MissionSteeringManager(missions), missions

    @pytest.mark.asyncio
    async def test_inject_task(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        plan = MagicMock()
        plan.tasks = [MagicMock()]
        mission.plan = plan
        missions[mission.id] = mission

        result = await sm.steer_mission(
            mission.id,
            "inject_task",
            task={"description": "Custom enum task", "phase": "discovery"},
        )
        assert "injected" in result["message"].lower()
        assert len(mission.plan.tasks) == 2

    @pytest.mark.asyncio
    async def test_set_param(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        missions[mission.id] = mission

        result = await sm.steer_mission(
            mission.id,
            "set_param",
            param_key="max_threads",
            param_value="10",
        )
        assert "max_threads" in result["message"]
        assert mission.steering_params["max_threads"] == "10"

    @pytest.mark.asyncio
    async def test_set_automation_level(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        missions[mission.id] = mission

        result = await sm.steer_mission(
            mission.id,
            "set_automation_level",
            automation_level="semi_auto",
        )
        assert "semi_auto" in result["message"]
        assert mission.automation_level == "semi_auto"

    @pytest.mark.asyncio
    async def test_set_automation_level_invalid(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        missions[mission.id] = mission

        with pytest.raises(ValueError, match="Invalid automation level"):
            await sm.steer_mission(
                mission.id,
                "set_automation_level",
                automation_level="turbo",
            )

    @pytest.mark.asyncio
    async def test_go_back(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        plan = MagicMock()
        task0 = MagicMock()
        task0.phase.value = "discovery"
        task1 = MagicMock()
        task1.phase.value = "enumeration"
        plan.tasks = [task0, task1]
        mission.plan = plan
        mission.current_task_index = 1
        missions[mission.id] = mission

        result = await sm.steer_mission(
            mission.id,
            "go_back",
            phase="discovery",
        )
        assert "discovery" in result["message"]
        assert mission.current_task_index == 0

    @pytest.mark.asyncio
    async def test_skip_target(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        missions[mission.id] = mission

        result = await sm.steer_mission(
            mission.id,
            "skip_target",
            target="192.168.1.50",
        )
        assert "skipped" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_steer_invalid_action(self, steering_manager):
        sm, missions = steering_manager
        mission = Mission("target.com", "test")
        missions[mission.id] = mission

        with pytest.raises(ValueError, match="Invalid action"):
            await sm.steer_mission(mission.id, "nonexistent_action")


# --- TOOL-007: Tool Output Caching ---


class TestToolResultCache:
    """Tests for enhanced tool result caching."""

    def test_cache_set_and_get(self):
        cache = ToolResultCache(ttl_seconds=60)
        cache.set("nmap", "192.168.1.1", {"ports": "80"}, {"result": "open"})

        result = cache.get("nmap", "192.168.1.1", {"ports": "80"})
        assert result == {"result": "open"}

    def test_cache_miss(self):
        cache = ToolResultCache(ttl_seconds=60)
        result = cache.get("nmap", "192.168.1.1", {"ports": "80"})
        assert result is None

    def test_cache_expired(self):
        cache = ToolResultCache(ttl_seconds=0)
        cache.set("nmap", "192.168.1.1", {}, {"result": "open"})
        # TTL=0 means cache expires immediately; sleep ensures time passes so expiry check triggers
        time.sleep(0.01)
        result = cache.get("nmap", "192.168.1.1", {})
        assert result is None

    def test_cache_force_bypass(self):
        cache = ToolResultCache(ttl_seconds=3600)
        cache.set("nmap", "192.168.1.1", {}, {"result": "open"})
        result = cache.get("nmap", "192.168.1.1", {}, force=True)
        assert result is None

    def test_cache_stats(self):
        cache = ToolResultCache(ttl_seconds=60)
        cache.set("nmap", "192.168.1.1", {}, "data")

        cache.get("nmap", "192.168.1.1", {})  # hit
        cache.get("nmap", "192.168.1.2", {})  # miss

        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate_pct"] == 50.0

    def test_cache_uses_sha256(self):
        cache = ToolResultCache(ttl_seconds=60)
        key = cache._key("nmap", "192.168.1.1", {})
        assert len(key) == 64  # SHA256 hex digest length

    def test_cache_clear_resets_stats(self):
        cache = ToolResultCache(ttl_seconds=60)
        cache.set("nmap", "192.168.1.1", {}, "data")
        cache.get("nmap", "192.168.1.1", {})
        cache.clear()

        assert cache.size == 0
        assert cache.stats["hits"] == 0
        assert cache.stats["misses"] == 0

    def test_cache_default_ttl_is_one_hour(self):
        cache = ToolResultCache()
        assert cache.ttl == 3600


# --- TOOL-005: Stealth Builder ---


class TestStealthBuilder:
    """Tests for stealth args application in command builder."""

    def test_apply_stealth_args_adds_flags(self):
        from app.services.tools.adapter.builder import CommandBuilder
        from app.services.tools.models import StealthConfig

        config = MagicMock()
        config.execution.arg_modifiers = None
        builder = CommandBuilder(config)

        stealth = StealthConfig(extra_args={"--threads": "5", "--rate-limit": "20"})
        cmd = builder.apply_stealth_args("feroxbuster --url http://target", stealth)

        assert "--threads 5" in cmd
        assert "--rate-limit 20" in cmd

    def test_apply_stealth_args_skips_existing(self):
        from app.services.tools.adapter.builder import CommandBuilder

        config = MagicMock()
        config.execution.arg_modifiers = None
        builder = CommandBuilder(config)

        stealth = MagicMock()
        stealth.extra_args = {"--threads": "5"}
        cmd = builder.apply_stealth_args("feroxbuster --threads 10 --url http://target", stealth)

        # Should not duplicate --threads
        assert cmd.count("--threads") == 1

    def test_apply_stealth_args_empty(self):
        from app.services.tools.adapter.builder import CommandBuilder

        config = MagicMock()
        config.execution.arg_modifiers = None
        builder = CommandBuilder(config)

        stealth = MagicMock()
        stealth.extra_args = {}
        cmd = builder.apply_stealth_args("nmap 192.168.1.1", stealth)
        assert cmd == "nmap 192.168.1.1"

    def test_apply_stealth_args_none_config(self):
        from app.services.tools.adapter.builder import CommandBuilder

        config = MagicMock()
        config.execution.arg_modifiers = None
        builder = CommandBuilder(config)

        cmd = builder.apply_stealth_args("nmap 192.168.1.1", None)
        assert cmd == "nmap 192.168.1.1"


# --- TOOL-009: Plugin Examples ---


class TestPluginExamples:
    """Tests that all plugins have examples."""

    def test_all_plugins_have_examples(self):
        import json
        from pathlib import Path

        plugins_dir = Path("plugins")
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                plugin = json.load(f)
            assert "examples" in plugin, f"{plugin_file.name} missing 'examples' field"
            assert len(plugin["examples"]) >= 2, f"{plugin_file.name} has fewer than 2 examples"

    def test_examples_have_required_fields(self):
        import json
        from pathlib import Path

        plugins_dir = Path("plugins")
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                plugin = json.load(f)
            if "examples" not in plugin:
                continue
            for ex in plugin["examples"]:
                assert "description" in ex, f"{plugin_file.name} example missing 'description'"
                assert "args" in ex, f"{plugin_file.name} example missing 'args'"
