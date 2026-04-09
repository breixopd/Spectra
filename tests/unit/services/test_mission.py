"""
Tests for the Mission class and attack surface tracking.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.models.attack_surface import (
    AttackVector,
    VectorPriority,
)
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


class TestMissionCreation:
    """Tests for Mission initialization."""

    def test_mission_creates_with_target_and_directive(self):
        """Mission should initialize with target and directive."""
        mission = Mission("192.168.1.1", "Full security assessment")

        assert mission.target == "192.168.1.1"
        assert mission.directive == "Full security assessment"
        assert mission.status == "created"
        assert mission.id is not None
        assert len(mission.id) == 36  # UUID format

    def test_mission_initializes_empty_collections(self):
        """Mission should start with empty findings, logs, tools_run."""
        mission = Mission("example.com", "Recon only")

        assert mission.findings == []
        assert mission.logs == []
        assert mission.tools_run == []
        assert mission.skipped_phases == set()

    def test_mission_has_attack_surface(self):
        """Mission should have an attack surface tracker."""
        mission = Mission("10.0.0.0/24", "Network scan")

        assert mission.attack_surface is not None
        assert mission.attack_surface.services == []
        assert mission.attack_surface.vulnerabilities == []


class TestMissionToolTracking:
    """Tests for tool execution tracking."""

    def test_record_tool_run_adds_to_list(self):
        """record_tool_run should add tool to tools_run."""
        mission = Mission("target.com", "test")

        mission.record_tool_run("nmap")
        mission.record_tool_run("nuclei")

        assert "nmap" in mission.tools_run
        assert "nuclei" in mission.tools_run
        assert len(mission.tools_run) == 2

    def test_record_tool_run_deduplicates(self):
        """record_tool_run should not add duplicates."""
        mission = Mission("target.com", "test")

        mission.record_tool_run("nmap")
        mission.record_tool_run("nmap")
        mission.record_tool_run("nmap")

        assert mission.tools_run.count("nmap") == 1


class TestMissionServiceTracking:
    """Tests for get_known_services."""

    def test_get_known_services_empty_initially(self):
        """get_known_services returns empty list initially."""
        mission = Mission("target.com", "test")

        services = mission.get_known_services()
        assert services == []

    def test_get_known_services_returns_added_services(self):
        """get_known_services returns services as dicts."""
        mission = Mission("192.168.1.1", "test")

        mission.add_service(host="192.168.1.1", port=22, service="ssh", product="OpenSSH", version="8.9")
        mission.add_service(host="192.168.1.1", port=80, service="http", product="nginx")

        services = mission.get_known_services()

        assert len(services) == 2
        assert services[0]["port"] == 22
        assert services[0]["service"] == "ssh"
        assert services[1]["port"] == 80


class TestMissionVulnTracking:
    """Tests for get_known_vulns."""

    def test_get_known_vulns_empty_initially(self):
        """get_known_vulns returns empty list initially."""
        mission = Mission("target.com", "test")

        vulns = mission.get_known_vulns()
        assert vulns == []

    def test_get_known_vulns_returns_added_vulns(self):
        """get_known_vulns returns vulnerabilities as dicts."""
        mission = Mission("target.com", "test")

        mission.add_vulnerability(
            vuln_id="vuln-001",
            title="SQL Injection",
            severity="high",
            cve_id="CVE-2023-1234",
        )

        vulns = mission.get_known_vulns()

        assert len(vulns) == 1
        assert vulns[0]["name"] == "SQL Injection"
        assert vulns[0]["severity"] == "high"
        assert vulns[0]["cve_id"] == "CVE-2023-1234"


class TestMissionState:
    """Tests for mission state management."""

    def test_stop_sets_event(self):
        """stop() should set the stop event."""
        mission = Mission("target.com", "test")

        assert not mission.is_stopped()
        mission.stop()
        assert mission.is_stopped()
        assert mission.status == "stopping"

    def test_set_status_updates_status(self):
        """set_status should update the status field."""
        mission = Mission("target.com", "test")

        mission.set_status("running")
        assert mission.status == "running"

        mission.set_status("completed")
        assert mission.status == "completed"

    def test_to_dict_includes_all_fields(self):
        """to_dict should include all important fields."""
        mission = Mission("192.168.1.1", "Full assessment")
        mission.record_tool_run("nmap")
        mission.add_finding({"name": "Open port", "port": 22})

        data = mission.to_dict()

        assert data["target"] == "192.168.1.1"
        assert data["directive"] == "Full assessment"
        assert data["status"] == "created"
        assert data["findings_count"] == 1
        assert "nmap" in data["tools_run"]
        assert "attack_surface" in data


class TestAttackSurfaceIntegration:
    """Tests for attack surface integration."""

    def test_add_webapp_tracks_technologies(self):
        """add_webapp should track web applications."""
        mission = Mission("https://example.com", "Web assessment")

        webapp = mission.add_webapp(url="https://example.com", technologies=["WordPress", "PHP", "nginx"])

        assert webapp.url == "https://example.com"
        assert "WordPress" in webapp.technologies
        assert len(mission.attack_surface.web_apps) == 1

    def test_add_finding_broadcasts(self):
        """add_finding should store and (conceptually) broadcast."""
        mission = Mission("target.com", "test")

        mission.add_finding(
            {
                "name": "XSS Vulnerability",
                "severity": "medium",
                "url": "https://target.com/search",
            }
        )

        assert len(mission.findings) == 1
        assert mission.findings[0]["name"] == "XSS Vulnerability"


class TestAttackVectorManagement:
    """Tests for attack vector tracking."""

    def test_get_next_vector_returns_highest_priority(self):
        """get_next_vector should return highest priority pending vector."""
        mission = Mission("target.com", "test")

        # Add vectors with different priorities
        low_vector = AttackVector(
            id="vec-1",
            name="Low priority attack",
            description="A low priority vector",
            priority=VectorPriority.LOW,
            target_type="service",
            target_ref="target.com:80",
        )
        critical_vector = AttackVector(
            id="vec-2",
            name="Critical attack",
            description="A critical vector",
            priority=VectorPriority.CRITICAL,
            target_type="vulnerability",
            target_ref="CVE-2023-1234",
        )

        mission.attack_surface.add_vector(low_vector)
        mission.attack_surface.add_vector(critical_vector)

        next_vec = mission.attack_surface.get_next_vector()

        assert next_vec is not None
        assert next_vec.id == "vec-2"
        assert next_vec.priority == VectorPriority.CRITICAL

    def test_prioritize_vectors_boosts_matching(self):
        """prioritize_vectors should boost priority of matching vectors."""
        mission = Mission("target.com", "test")

        vector = AttackVector(
            id="vec-1",
            name="SSH Attack",
            description="Attack on SSH",
            priority=VectorPriority.LOW,
            target_type="service",
            target_ref="ssh:22",
        )
        mission.attack_surface.add_vector(vector)

        # Prioritize SSH
        mission.attack_surface.prioritize_vectors(["ssh"])

        # Should have been boosted
        assert mission.attack_surface.vectors[0].priority == VectorPriority.MEDIUM
