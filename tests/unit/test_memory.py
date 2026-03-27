"""Tests for the persistent Mission Memory system."""

import pytest

from app.services.ai.memory import (
    MissionMemory,
    detect_os_from_output,
    detect_os_from_services,
    get_memory,
)


@pytest.fixture
def memory(tmp_path):
    return MissionMemory(memory_dir=tmp_path)


class TestToolLessons:
    def test_record_and_retrieve(self, memory):
        memory.record_tool_result(
            tool_id="nmap",
            target_service="http",
            success=True,
            findings_count=5,
            finding_types=["port_scan", "service_detection"],
            target_product="Apache",
            target_version="2.4.25",
        )
        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 1
        assert recs[0]["tool"] == "nmap"
        assert "findings" in recs[0]["reason"]

    def test_failed_tools_excluded(self, memory):
        memory.record_tool_result("nmap", "http", success=False, findings_count=0)
        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 0

    def test_zero_findings_excluded(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=0)
        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 0

    def test_service_matching_case_insensitive(self, memory):
        memory.record_tool_result("nuclei", "HTTP", success=True, findings_count=3)
        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 1

    def test_product_boosts_relevance(self, memory):
        memory.record_tool_result("nuclei", "http", success=True, findings_count=2, target_product="Apache")
        memory.record_tool_result("nikto", "http", success=True, findings_count=1)
        recs = memory.get_tool_recommendations("http", product="Apache")
        assert recs[0]["tool"] == "nuclei"

    def test_os_boosts_relevance(self, memory):
        memory.record_tool_result("nmap", "ssh", success=True, findings_count=1, target_os="linux")
        memory.record_tool_result("nmap", "ssh", success=True, findings_count=1, target_os="windows")
        recs = memory.get_tool_recommendations("ssh", os_family="linux")
        assert len(recs) >= 1

    def test_deduplicates_tools(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=3)
        memory.record_tool_result("nmap", "http", success=True, findings_count=5)
        recs = memory.get_tool_recommendations("http")
        assert len(recs) == 1

    def test_max_recommendations(self, memory):
        for i in range(10):
            memory.record_tool_result(f"tool-{i}", "http", success=True, findings_count=i + 1)
        recs = memory.get_tool_recommendations("http")
        assert len(recs) <= 5


class TestExploitLessons:
    def test_record_and_retrieve(self, memory):
        memory.record_exploit_success(
            target_service="http",
            exploit_tool="sqlmap",
            target_product="Apache",
            target_version="2.4.25",
            attack_chain=["nmap scan", "nuclei vuln", "sqlmap exploit"],
            access_level="user",
            cve_id="CVE-2021-41773",
        )
        history = memory.get_exploit_history("http")
        assert len(history) == 1
        assert history[0].exploit_tool == "sqlmap"
        assert history[0].cve_id == "CVE-2021-41773"
        assert len(history[0].attack_chain) == 3

    def test_filter_by_product(self, memory):
        memory.record_exploit_success("http", "sqlmap", target_product="Apache")
        memory.record_exploit_success("http", "hydra", target_product="Nginx")
        history = memory.get_exploit_history("http", product="Apache")
        assert len(history) == 1
        assert history[0].exploit_tool == "sqlmap"

    def test_max_results(self, memory):
        for i in range(10):
            memory.record_exploit_success("ssh", f"exploit-{i}")
        history = memory.get_exploit_history("ssh")
        assert len(history) <= 5


class TestTargetProfiles:
    def test_create_and_update(self, memory):
        memory.update_target_profile(
            os_family="linux",
            effective_tools=["nmap", "nuclei"],
            note="Common web server target",
        )
        profile = memory.get_os_strategy("linux")
        assert profile is not None
        assert "nmap" in profile.effective_tools
        assert "Common web server target" in profile.notes

    def test_accumulates_tools(self, memory):
        memory.update_target_profile("linux", effective_tools=["nmap"])
        memory.update_target_profile("linux", effective_tools=["nuclei"])
        profile = memory.get_os_strategy("linux")
        assert "nmap" in profile.effective_tools
        assert "nuclei" in profile.effective_tools

    def test_no_duplicates(self, memory):
        memory.update_target_profile("linux", effective_tools=["nmap"])
        memory.update_target_profile("linux", effective_tools=["nmap"])
        profile = memory.get_os_strategy("linux")
        assert profile.effective_tools.count("nmap") == 1

    def test_case_insensitive_lookup(self, memory):
        memory.update_target_profile("Linux", effective_tools=["nmap"])
        assert memory.get_os_strategy("linux") is not None

    def test_nonexistent_returns_none(self, memory):
        assert memory.get_os_strategy("qnx") is None


class TestFalsePositives:
    def test_record_and_check(self, memory):
        assert not memory.is_false_positive("http-missing-headers")
        memory.record_false_positive("http-missing-headers")
        assert memory.is_false_positive("http-missing-headers")

    def test_persists_across_loads(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.record_false_positive("noisy-template")
        m2 = MissionMemory(memory_dir=tmp_path)
        assert m2.is_false_positive("noisy-template")


class TestPersistence:
    def test_tool_lessons_persist(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.record_tool_result("nmap", "http", success=True, findings_count=3)
        m2 = MissionMemory(memory_dir=tmp_path)
        assert len(m2.tool_lessons) == 1
        assert m2.tool_lessons[0].tool_id == "nmap"

    def test_exploit_lessons_persist(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.record_exploit_success("ssh", "hydra", access_level="root")
        m2 = MissionMemory(memory_dir=tmp_path)
        assert len(m2.exploit_lessons) == 1

    def test_profiles_persist(self, tmp_path):
        m1 = MissionMemory(memory_dir=tmp_path)
        m1.update_target_profile("windows", effective_tools=["nmap"])
        m2 = MissionMemory(memory_dir=tmp_path)
        assert "windows" in m2.target_profiles

    def test_corrupted_file_handled(self, tmp_path):
        (tmp_path / "tool_lessons.json").write_text("not json{{{")
        m = MissionMemory(memory_dir=tmp_path)
        assert len(m.tool_lessons) == 0


class TestPromptContext:
    def test_empty_memory_returns_empty(self, memory):
        assert memory.get_context_for_prompt("http") == ""

    def test_includes_tool_recommendations(self, memory):
        memory.record_tool_result("nuclei", "http", success=True, findings_count=5, target_product="Apache")
        ctx = memory.get_context_for_prompt(service="http")
        assert "nuclei" in ctx
        assert "Past Experience" in ctx

    def test_includes_exploit_history(self, memory):
        memory.record_exploit_success(
            "http",
            "sqlmap",
            cve_id="CVE-2021-1234",
            attack_chain=["nmap", "nuclei", "sqlmap"],
            access_level="root",
        )
        ctx = memory.get_context_for_prompt(service="http")
        assert "CVE-2021-1234" in ctx
        assert "root access" in ctx

    def test_includes_os_strategy(self, memory):
        memory.update_target_profile("linux", effective_tools=["nmap", "nuclei"])
        ctx = memory.get_context_for_prompt(os_family="linux")
        assert "Linux Strategy" in ctx
        assert "nmap" in ctx

    def test_combined_context(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=3)
        memory.record_exploit_success("http", "sqlmap", access_level="user")
        memory.update_target_profile("linux", effective_tools=["nuclei"])
        ctx = memory.get_context_for_prompt("http", os_family="linux")
        assert "Past Experience" in ctx
        assert "Successful Exploits" in ctx
        assert "Linux Strategy" in ctx


class TestOSDetection:
    def test_linux_from_banner(self):
        assert detect_os_from_output("Ubuntu 20.04 LTS") == "linux"

    def test_windows_from_banner(self):
        assert detect_os_from_output("Microsoft IIS/10.0") == "windows"

    def test_windows_from_smb(self):
        assert detect_os_from_output("SMB signing enabled, NTLM auth") == "windows"

    def test_freebsd(self):
        assert detect_os_from_output("FreeBSD 13.1-RELEASE") == "freebsd"

    def test_embedded(self):
        assert detect_os_from_output("MikroTik RouterOS 6.49") == "embedded"

    def test_unknown(self):
        assert detect_os_from_output("some random text") == "unknown"

    def test_from_services(self):
        services = [
            {"product": "Apache", "version": "2.4.41", "service": "http"},
            {"product": "OpenSSH", "version": "8.2p1 Ubuntu", "service": "ssh"},
        ]
        assert detect_os_from_services(services) == "linux"

    def test_from_services_windows(self):
        services = [
            {"product": "Microsoft IIS", "version": "10.0", "service": "http"},
            {"product": "Microsoft HTTPAPI", "version": "2.0", "service": "http"},
        ]
        assert detect_os_from_services(services) == "windows"


class TestStats:
    def test_returns_counts(self, memory):
        memory.record_tool_result("nmap", "http", success=True, findings_count=1)
        memory.record_exploit_success("http", "sqlmap")
        memory.update_target_profile("linux")
        memory.record_false_positive("noisy")
        stats = memory.get_stats()
        assert stats["tool_lessons"] == 1
        assert stats["exploit_lessons"] == 1
        assert stats["target_profiles"] == 1
        assert stats["false_positives"] == 1


class TestSingleton:
    def test_get_memory_returns_same(self, tmp_path):
        import app.services.ai.memory as mod
        from unittest.mock import patch

        mod._memory = None
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(mod, "MissionMemory", side_effect=lambda *a, **kw: mod.MissionMemory.__new__(mod.MissionMemory)):
            pass  # skip patching constructor, use different approach
        # Directly set _memory to a real instance with tmp_path
        m_inst = mod.MissionMemory(memory_dir=cache_dir)
        mod._memory = None
        with patch.object(mod, "MissionMemory", return_value=m_inst):
            m1 = mod.get_memory()
            m2 = mod.get_memory()
        assert m1 is m2
        mod._memory = None
