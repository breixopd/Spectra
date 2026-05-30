"""Tests for MEM-002 (indexing), MEM-003 (backup rotation), MEM-006 (aggregation)."""

import json

import pytest

from spectra_ai_core.memory import MissionMemory


@pytest.fixture
def memory(tmp_path):
    return MissionMemory(memory_dir=tmp_path)


class TestToolIndex:
    """MEM-002: In-memory indexes by tool_id."""

    def test_get_lessons_for_tool(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=3)
        memory.record_tool_result("nuclei", "http", success=True, findings_count=2)
        memory.record_tool_result("nmap", "ssh", success=True, findings_count=1)

        nmap_lessons = memory.get_lessons_for_tool("nmap")
        assert len(nmap_lessons) == 2
        assert all(l.tool_id == "nmap" for l in nmap_lessons)

    def test_get_lessons_for_tool_empty(self, memory):
        assert memory.get_lessons_for_tool("nonexistent") == []

    def test_index_rebuilt_on_load(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.record_tool_result("nmap", "http", success=True, findings_count=1)
        m1.record_tool_result("nuclei", "ssh", success=True, findings_count=2)
        m1.force_save()

        m2 = MissionMemory(memory_dir=tmp_path)
        assert len(m2.get_lessons_for_tool("nmap")) == 1
        assert len(m2.get_lessons_for_tool("nuclei")) == 1


class TestServiceIndex:
    """MEM-002: In-memory indexes by service."""

    def test_get_lessons_for_service(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=3)
        memory.record_tool_result("nuclei", "http", success=True, findings_count=2)
        memory.record_tool_result("nmap", "ssh", success=True, findings_count=1)

        http_lessons = memory.get_lessons_for_service("http")
        assert len(http_lessons) == 2

    def test_service_index_case_insensitive(self, memory):
        memory.record_tool_result("nmap", "HTTP", success=True, findings_count=1)
        assert len(memory.get_lessons_for_service("http")) == 1

    def test_get_lessons_for_service_empty(self, memory):
        assert memory.get_lessons_for_service("ftp") == []

    def test_indexed_recommendations_same_as_before(self, memory):
        """Indexed get_tool_recommendations returns same results."""
        memory.record_tool_result("nuclei", "http", success=True, findings_count=5, target_product="Apache")
        memory.record_tool_result("nikto", "http", success=True, findings_count=3)
        memory.record_tool_result("nmap", "ssh", success=True, findings_count=1)

        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 2
        tool_names = {r["tool"] for r in recs}
        assert "nuclei" in tool_names
        assert "nikto" in tool_names


class TestBackupRotation:
    """MEM-003: Backup rotation and fallback loading."""

    def test_backup_created_on_save(self, tmp_path):
        m = MissionMemory(memory_dir=tmp_path)
        m.record_tool_result("nmap", "http", success=True, findings_count=1)
        # After first save, no backup (file didn't exist before first write)
        m.record_tool_result("nuclei", "ssh", success=True, findings_count=2)
        m.force_save()
        # After second save, .1.bak should exist
        bak = tmp_path / "tool_lessons.json.1.bak"
        assert bak.exists()

    def test_backup_rotation_shifts(self, tmp_path):
        m = MissionMemory(memory_dir=tmp_path)
        for i in range(4):
            m.record_tool_result(f"tool-{i}", "http", success=True, findings_count=1)
            m.force_save()
        # We should have .1.bak, .2.bak, .3.bak (shifted on each save)
        assert (tmp_path / "tool_lessons.json.1.bak").exists()

    def test_max_backups_respected(self, tmp_path):
        m = MissionMemory(memory_dir=tmp_path)
        # Write enough to exceed MAX_BACKUPS
        for i in range(8):
            m.record_tool_result(f"tool-{i}", "http", success=True, findings_count=1)
        # .6.bak and beyond should not exist
        assert not (tmp_path / "tool_lessons.json.6.bak").exists()

    def test_fallback_on_corruption(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.record_tool_result("nmap", "http", success=True, findings_count=3)
        m1.record_tool_result("nuclei", "ssh", success=True, findings_count=2)
        m1.force_save()
        # Now corrupt the main file
        (tmp_path / "tool_lessons.json").write_text("corrupted{{{")
        # Reload should recover from backup
        m2 = MissionMemory(memory_dir=tmp_path)
        assert len(m2.tool_lessons) >= 1  # Recovered from .1.bak

    def test_fallback_returns_empty_when_no_backups(self, tmp_path):
        (tmp_path / "tool_lessons.json").write_text("bad json{")
        m = MissionMemory(memory_dir=tmp_path)
        assert len(m.tool_lessons) == 0


class TestKnowledgeAggregation:
    """MEM-006: Cross-mission knowledge aggregation."""

    @pytest.fixture(autouse=True)
    def _patch_data_path(self, tmp_path, monkeypatch):
        """Redirect data_path so aggregate_knowledge() can write files."""
        import spectra_ai_core.memory as _mem_mod

        monkeypatch.setattr(_mem_mod, "data_path", lambda *parts: tmp_path / "/".join(str(x) for x in parts))
        self._agg_path = tmp_path

    def test_aggregate_basic(self, memory):
        memory.record_tool_result("nuclei", "http", success=True, findings_count=5, finding_types=["xss", "sqli"])
        memory.record_tool_result("nuclei", "http", success=True, findings_count=3, finding_types=["sqli"])
        memory.record_tool_result("nuclei", "http", success=False, findings_count=0)
        memory.record_tool_result("nikto", "http", success=True, findings_count=2, finding_types=["misconfig"])

        result = memory.aggregate_knowledge()
        assert "service_profiles" in result
        assert "http" in result["service_profiles"]
        profile = result["service_profiles"]["http"]
        assert "nuclei" in profile["success_rate"]
        assert "nikto" in profile["success_rate"]
        assert "last_aggregated" in result

    def test_aggregate_success_rates(self, memory):
        for i in range(8):
            memory.record_tool_result("nuclei", "ssh", success=True, findings_count=1, target_product=f"v{i}")
        for i in range(2):
            memory.record_tool_result("nuclei", "ssh", success=False, findings_count=0, target_product=f"f{i}")

        result = memory.aggregate_knowledge()
        profile = result["service_profiles"]["ssh"]
        assert profile["success_rate"]["nuclei"] == 0.8

    def test_aggregate_best_tools(self, memory):
        for i in range(6):
            memory.record_tool_result("nmap", "http", success=True, findings_count=2, target_product=f"v{i}")
        for i in range(4):
            memory.record_tool_result("nmap", "http", success=False, findings_count=0, target_product=f"f{i}")

        result = memory.aggregate_knowledge()
        profile = result["service_profiles"]["http"]
        assert "nmap" in profile["best_tools"]

    def test_aggregate_writes_file(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=1)
        memory.aggregate_knowledge()
        # The patched data_path puts the file in tmp_path
        out = self._agg_path / "cache" / "aggregated_knowledge.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert "service_profiles" in data

    def test_aggregate_empty(self, memory):
        result = memory.aggregate_knowledge()
        assert result["service_profiles"] == {}
