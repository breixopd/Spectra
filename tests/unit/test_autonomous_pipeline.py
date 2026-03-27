"""Tests for autonomous pipeline improvements across multiple modules."""

from unittest.mock import MagicMock

import pytest

from unittest.mock import patch


@pytest.fixture(autouse=True)
def _mission_runtime_isolation(tmp_path):
    with (
        patch("app.services.mission.mission.data_path", side_effect=lambda *parts: tmp_path.joinpath(*parts)),
        patch("app.services.mission.mission.asyncio.create_task"),
    ):
        yield

from app.services.ai.agents.exploit_crafter import ExploitCrafter
from app.services.ai.agents.tool_selector import ToolSelectorAgent
from app.services.ai.agents.vector_generator import VectorGeneratorAgent
from app.services.mission.executor.analysis import auto_expand_scope
from app.services.mission.executor.handlers import PHASE_TRANSITION_RULES, TaskDispatcher
from app.services.mission.mission import Mission
from app.services.mission.task_tree import TaskStatus

# ===== Mission Progress =====


class TestMissionProgress:
    def test_progress_empty_tree(self):
        mission = Mission("target.com", "test")
        progress = mission.get_progress()
        assert progress["percent"] == 0
        assert progress["total_tasks"] == 0

    def test_progress_no_completed_tasks(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.add_task("t2", "Task 2", "recon/nikto")
        progress = mission.get_progress()
        assert progress["percent"] == 0
        assert progress["total_tasks"] == 2
        assert progress["completed_tasks"] == 0

    def test_progress_some_completed(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.add_task("t2", "Task 2", "recon/nikto")
        mission.task_tree.add_task("t3", "Task 3", "exploit/rce")
        mission.task_tree.update_status("t1", TaskStatus.COMPLETED)
        progress = mission.get_progress()
        assert progress["percent"] == pytest.approx(33.3, abs=0.1)
        assert progress["completed_tasks"] == 1
        assert progress["total_tasks"] == 3

    def test_progress_all_completed(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.update_status("t1", TaskStatus.COMPLETED)
        progress = mission.get_progress()
        assert progress["percent"] == 100.0
        assert progress["completed_tasks"] == 1

    def test_progress_failed_counts_as_done(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.update_status("t1", TaskStatus.FAILED)
        progress = mission.get_progress()
        assert progress["completed_tasks"] == 1

    def test_progress_skipped_counts_as_done(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.update_status("t1", TaskStatus.SKIPPED)
        progress = mission.get_progress()
        assert progress["completed_tasks"] == 1

    def test_progress_active_tasks_listed(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "recon/nmap")
        mission.task_tree.update_status("t1", TaskStatus.ACTIVE)
        progress = mission.get_progress()
        assert len(progress["active_tasks"]) == 1
        assert progress["active_tasks"][0]["id"] == "t1"

    def test_progress_phase_from_active_task(self):
        mission = Mission("target.com", "test")
        mission.task_tree.add_task("t1", "Task 1", "exploit/rce")
        mission.task_tree.update_status("t1", TaskStatus.ACTIVE)
        progress = mission.get_progress()
        assert progress["phase"] == "exploit"


# ===== Auto Expand Scope =====


class TestAutoExpandScope:
    def test_expand_subdomain(self):
        findings = [{"type": "subdomain", "value": "api.example.com"}]
        expansions = auto_expand_scope(findings, {})
        assert len(expansions) == 1
        assert expansions[0]["type"] == "domain"
        assert expansions[0]["value"] == "api.example.com"
        assert expansions[0]["source"] == "auto-discovered"

    def test_expand_host_ip(self):
        findings = [{"type": "host", "value": "10.0.0.5"}]
        expansions = auto_expand_scope(findings, {})
        assert len(expansions) == 1
        assert expansions[0]["type"] == "ip"
        assert expansions[0]["source"] == "pivot-discovered"

    def test_no_duplicate_expansions(self):
        findings = [
            {"type": "host", "value": "10.0.0.5"},
            {"type": "host", "value": "10.0.0.5"},
        ]
        expansions = auto_expand_scope(findings, {})
        assert len(expansions) == 1

    def test_skip_already_in_scope(self):
        findings = [{"type": "host", "value": "192.168.1.1"}]
        current_scope = {"target": "192.168.1.1"}
        expansions = auto_expand_scope(findings, current_scope)
        assert len(expansions) == 0

    def test_empty_findings(self):
        expansions = auto_expand_scope([], {})
        assert expansions == []

    def test_irrelevant_types_ignored(self):
        findings = [{"type": "vulnerability", "value": "CVE-2021-1234"}]
        expansions = auto_expand_scope(findings, {})
        assert expansions == []


# ===== Exploit Crafter Improvements =====


class TestExploitCrafterDeterministic:
    def setup_method(self):
        self.mock_llm = MagicMock()
        self.crafter = ExploitCrafter(self.mock_llm)

    def test_service_exploit_map_exists(self):
        assert len(ExploitCrafter.SERVICE_EXPLOIT_MAP) > 0

    def test_get_deterministic_exploits_apache(self):
        info = {"product": "Apache/2.4.49", "version": ""}
        exploits = self.crafter.get_deterministic_exploits(info)
        assert "exploit/multi/http/apache_normalize_path_rce" in exploits

    def test_get_deterministic_exploits_vsftpd(self):
        info = {"product": "vsftpd", "version": "2.3.4"}
        exploits = self.crafter.get_deterministic_exploits(info)
        assert "exploit/unix/ftp/vsftpd_234_backdoor" in exploits

    def test_get_deterministic_exploits_no_match(self):
        info = {"product": "UnknownProduct", "version": "1.0"}
        exploits = self.crafter.get_deterministic_exploits(info)
        assert exploits == []

    def test_get_deterministic_exploits_empty_info(self):
        info = {}
        exploits = self.crafter.get_deterministic_exploits(info)
        assert exploits == []

    def test_get_deterministic_exploits_wordpress(self):
        info = {"product": "WordPress", "version": "5.8"}
        exploits = self.crafter.get_deterministic_exploits(info)
        assert "exploit/unix/webapp/wp_admin_shell_upload" in exploits

    def test_select_payload_linux_default(self):
        payload = ExploitCrafter.select_payload("linux", attempt=1)
        assert "linux" in payload
        assert "meterpreter" in payload

    def test_select_payload_windows(self):
        payload = ExploitCrafter.select_payload("windows", attempt=1)
        assert "windows" in payload
        assert "meterpreter" in payload

    def test_select_payload_fallback_on_retry(self):
        p1 = ExploitCrafter.select_payload("linux", attempt=1)
        p2 = ExploitCrafter.select_payload("linux", attempt=2)
        p3 = ExploitCrafter.select_payload("linux", attempt=3)
        assert p1 != p2  # meterpreter vs generic
        assert "generic" in p2 or "shell_reverse" in p2
        assert "bind" in p3

    def test_select_payload_none_os_defaults_linux(self):
        payload = ExploitCrafter.select_payload(None, attempt=1)
        assert "linux" in payload

    def test_select_payload_clamps_attempt(self):
        # Very high attempt should still return a valid payload
        payload = ExploitCrafter.select_payload("linux", attempt=100)
        assert payload  # Should not error


# ===== Vector Generator Deterministic =====


class TestVectorGeneratorDeterministic:
    def test_generate_http_vectors(self):
        services = {80: "http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        assert len(vectors) > 0
        names = [v["name"] for v in vectors]
        assert "Directory Brute Force" in names
        assert "Web Vulnerability Scan" in names

    def test_generate_smb_vectors(self):
        services = {445: "microsoft-ds smb"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "SMB Enumeration" in names

    def test_generate_ssh_vectors(self):
        services = {22: "ssh"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "SSH Version Check" in names
        assert "SSH Brute Force" in names

    def test_generate_ftp_vectors(self):
        services = {21: "ftp"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "Anonymous FTP Check" in names

    def test_generate_mysql_vectors(self):
        services = {3306: "mysql"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        assert len(vectors) > 0
        assert any(v["target_port"] == 3306 for v in vectors)

    def test_generate_dns_vectors(self):
        services = {53: "dns"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "DNS Zone Transfer" in names

    def test_empty_services(self):
        vectors = VectorGeneratorAgent.generate_deterministic_vectors({})
        assert vectors == []

    def test_unknown_service(self):
        services = {9999: "unknownprotocol"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        assert vectors == []

    def test_vectors_have_target_port(self):
        services = {8080: "http-proxy http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        for v in vectors:
            assert "target_port" in v
            assert v["target_port"] == 8080

    def test_multiple_services(self):
        services = {22: "ssh", 80: "http", 445: "smb"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        ports = {v["target_port"] for v in vectors}
        assert 22 in ports
        assert 80 in ports
        assert 445 in ports


# ===== Tool Selector Quick Select =====


class TestToolSelectorQuickSelect:
    def setup_method(self):
        self.mock_llm = MagicMock()
        self.agent = ToolSelectorAgent(self.mock_llm)

    def test_quick_select_http_recon(self):
        result = self.agent._quick_select("http", "recon", [])
        assert result is not None
        assert "whatweb" in result

    def test_quick_select_smb_recon(self):
        result = self.agent._quick_select("smb", "recon", [])
        assert result is not None
        assert "enum4linux" in result

    def test_quick_select_ssh_exploitation(self):
        result = self.agent._quick_select("ssh", "exploitation", [])
        assert result is not None
        assert "hydra" in result

    def test_quick_select_unknown_service(self):
        result = self.agent._quick_select("unknownservice", "recon", [])
        assert result is None

    def test_quick_select_unknown_phase(self):
        result = self.agent._quick_select("http", "unknown_phase", [])
        assert result is None

    def test_quick_select_filters_already_run(self):
        result = self.agent._quick_select("http", "recon", ["whatweb", "dirsearch"])
        assert result is not None
        assert "whatweb" not in result
        assert "nikto" in result

    def test_quick_select_all_run_returns_none(self):
        result = self.agent._quick_select("http", "recon", ["whatweb", "dirsearch", "nikto"])
        assert result is None

    def test_quick_select_wordpress(self):
        result = self.agent._quick_select("wordpress", "recon", [])
        assert result is not None
        assert "wpscan" in result

    def test_quick_select_dns(self):
        result = self.agent._quick_select("dns", "recon", [])
        assert result is not None
        assert "subfinder" in result

    def test_quick_select_mysql_exploitation(self):
        result = self.agent._quick_select("mysql", "exploitation", [])
        assert result is not None
        assert "hydra" in result


# ===== Phase Transition Rules =====


class TestPhaseTransitionRules:
    def test_rules_exist(self):
        assert "recon" in PHASE_TRANSITION_RULES
        assert "vuln_scan" in PHASE_TRANSITION_RULES
        assert "exploitation" in PHASE_TRANSITION_RULES
        assert "post_exploitation" in PHASE_TRANSITION_RULES

    def test_recon_rules(self):
        rules = PHASE_TRANSITION_RULES["recon"]
        assert rules["min_tools"] == 2
        assert rules["max_tools"] == 6
        assert rules["transition_trigger"] == "services_found"

    def test_exploitation_has_max_failures(self):
        rules = PHASE_TRANSITION_RULES["exploitation"]
        assert "max_failures" in rules
        assert rules["max_failures"] == 3


class TestShouldTransitionPhase:
    def setup_method(self):
        self.dispatcher = TaskDispatcher(
            tool_service=MagicMock(),
            exploitation_manager=MagicMock(),
            consensus=MagicMock(),
            agents={},
        )

    def test_unknown_phase_returns_false(self):
        mission = Mission("target.com", "test")
        assert self.dispatcher.should_transition_phase(mission, "unknown") is False

    def test_recon_below_min_tools(self):
        mission = Mission("target.com", "test")
        # 0 tool executions → below min_tools for recon (2)
        assert self.dispatcher.should_transition_phase(mission, "recon") is False

    def test_recon_max_tools_reached(self):
        mission = Mission("target.com", "test")
        for i in range(7):
            mission.tool_executions.append({"tool": f"tool{i}", "success": True})
        assert self.dispatcher.should_transition_phase(mission, "recon") is True

    def test_recon_services_found(self):
        mission = Mission("target.com", "test")
        # Add 2 successful executions and a service
        mission.tool_executions.append({"tool": "nmap", "success": True})
        mission.tool_executions.append({"tool": "naabu", "success": True})
        mission.add_service("target.com", 80, "http")
        assert self.dispatcher.should_transition_phase(mission, "recon") is True

    def test_exploitation_max_failures(self):
        mission = Mission("target.com", "test")
        mission.tool_executions.append({"tool": "msf1", "success": True})
        for i in range(4):
            mission.tool_executions.append({"tool": f"exploit{i}", "success": False})
        assert self.dispatcher.should_transition_phase(mission, "exploitation") is True
