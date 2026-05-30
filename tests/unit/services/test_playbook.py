"""Tests for the Playbook System."""

import pytest

from spectra_ai_core.playbook import (
    ExploitPattern,
    PlaybookEngine,
    PlaybookStep,
    ServicePlaybook,
    get_playbook_engine,
)


class TestPlaybookEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return PlaybookEngine(patterns_file=tmp_path / "patterns.json")

    def test_loads_default_playbooks(self, engine):
        assert len(engine.playbooks) > 0
        services = [pb.service for pb in engine.playbooks]
        assert "http" in services
        assert "ssh" in services
        assert "smb" in services

    def test_get_playbook_by_service(self, engine):
        pb = engine.get_playbook_for_service("http")
        assert pb is not None
        assert pb.service == "http"
        assert len(pb.steps) > 0

    def test_get_playbook_by_port(self, engine):
        pb = engine.get_playbook_for_service("unknown", port=22)
        assert pb is not None
        assert pb.service == "ssh"

    def test_get_playbook_nonexistent(self, engine):
        pb = engine.get_playbook_for_service("exotic-protocol", port=99999)
        assert pb is None

    def test_get_recommended_tools(self, engine):
        services = [
            {"service": "http", "port": 80, "product": "Apache"},
            {"service": "ssh", "port": 22, "product": "OpenSSH"},
        ]
        recs = engine.get_recommended_tools(services)
        assert len(recs) > 0
        tool_names = [r["tool"] for r in recs]
        assert "nmap" in tool_names

    def test_filters_already_run(self, engine):
        services = [{"service": "http", "port": 80}]
        recs_all = engine.get_recommended_tools(services)
        recs_filtered = engine.get_recommended_tools(services, tools_already_run=["nmap"])
        assert len(recs_filtered) < len(recs_all)
        assert not any(r["tool"] == "nmap" for r in recs_filtered)

    def test_deduplicates_tools(self, engine):
        services = [
            {"service": "http", "port": 80},
            {"service": "http", "port": 8080},
        ]
        recs = engine.get_recommended_tools(services)
        tool_names = [r["tool"] for r in recs]
        assert len(tool_names) == len(set(tool_names))

    def test_recommendation_has_reasoning(self, engine):
        services = [{"service": "ssh", "port": 22}]
        recs = engine.get_recommended_tools(services)
        for rec in recs:
            assert "reason" in rec
            assert len(rec["reason"]) > 10

    def test_grounded_prompt_context(self, engine):
        services = [
            {"service": "http", "port": 80, "product": "nginx"},
        ]
        context = engine.get_grounded_prompt_context(services)
        assert "Playbook Recommendations" in context
        assert "confirmed services" in context.lower()

    def test_grounded_context_empty(self, engine):
        context = engine.get_grounded_prompt_context([])
        assert context == ""

    def test_record_success_new(self, engine):
        engine.record_success("http", "nuclei", product="Apache")
        assert len(engine.exploit_patterns) == 1
        assert engine.exploit_patterns[0].service == "http"
        assert engine.exploit_patterns[0].tool == "nuclei"
        assert engine.exploit_patterns[0].success_rate == 0.5

    def test_record_success_existing_boosts(self, engine):
        engine.record_success("http", "nuclei")
        engine.record_success("http", "nuclei")
        assert len(engine.exploit_patterns) == 1
        assert engine.exploit_patterns[0].success_rate > 0.5

    def test_record_success_caps_at_one(self, engine):
        for _ in range(20):
            engine.record_success("http", "nuclei")
        assert engine.exploit_patterns[0].success_rate <= 1.0


class TestPlaybookStep:
    def test_create(self):
        step = PlaybookStep(
            tool="nmap",
            description="Port scan",
            args={"ports": "1-1000"},
        )
        assert step.tool == "nmap"
        assert step.condition is None

    def test_with_condition(self):
        step = PlaybookStep(
            tool="sqlmap",
            description="SQL injection",
            condition="parameters_found",
        )
        assert step.condition == "parameters_found"


class TestServicePlaybook:
    def test_create(self):
        pb = ServicePlaybook(
            service="http",
            ports=[80, 443],
            steps=[PlaybookStep(tool="nmap", description="Scan")],
            tags=["web"],
        )
        assert pb.service == "http"
        assert len(pb.steps) == 1
        assert "web" in pb.tags


class TestExploitPattern:
    def test_create(self):
        pattern = ExploitPattern(
            service="ssh",
            product="OpenSSH",
            version_regex=r"7\.\d",
            tool="searchsploit",
            success_rate=0.8,
        )
        assert pattern.service == "ssh"
        assert pattern.success_rate == 0.8


class TestSingleton:
    def test_get_playbook_engine_returns_same(self):
        import spectra_ai_core.playbook as mod

        mod._engine = None
        e1 = get_playbook_engine()
        e2 = get_playbook_engine()
        assert e1 is e2
        mod._engine = None


class TestHTTPPlaybook:
    def test_http_playbook_steps_order(self):
        engine = PlaybookEngine()
        pb = engine.get_playbook_for_service("http")
        assert pb is not None
        tools = [s.tool for s in pb.steps]
        assert tools[0] == "nmap"
        assert "nuclei" in tools
        assert "nikto" in tools

    def test_wordpress_playbook(self):
        engine = PlaybookEngine()
        pb = engine.get_playbook_for_service("wordpress")
        assert pb is not None
        tools = [s.tool for s in pb.steps]
        assert "wpscan" in tools

    def test_add_playbook_dynamic(self):
        """Test that adding a playbook dynamically rebuilds the indices for O(1) lookups."""
        engine = PlaybookEngine()
        new_pb = ServicePlaybook(
            service="custom_service",
            ports=[9999],
            steps=[PlaybookStep(tool="custom_tool", description="Custom tool test")],
            tags=["custom"],
        )

        # Add the playbook dynamically
        engine.add_playbook(new_pb)

        # Verify it can be found by service name
        found_by_svc = engine.get_playbook_for_service("custom_service")
        assert found_by_svc is not None
        assert found_by_svc.service == "custom_service"

        # Verify it can be found by port
        found_by_port = engine.get_playbook_for_service("unknown", port=9999)
        assert found_by_port is not None
        assert found_by_port.service == "custom_service"
