"""Tests for Mission entity (app/services/mission/mission.py)."""

from unittest.mock import patch

import pytest

from app.services.mission.credentials import Credential
from app.services.mission.mission import Mission


@pytest.fixture
def mission():
    with patch("app.services.mission.mission.get_blackboard") as mock_bb:
        mock_bb.return_value = type("BB", (), {
            "write": lambda self, k, v, **kw: None,
            "read": lambda self, k, **kw: None,
            "read_all": lambda self: {},
        })()
        m = Mission(target="10.0.0.1", directive="Test scan")
        yield m


class TestMissionStateTransitions:
    def test_initial_status_is_created(self, mission):
        assert mission.status == "created"

    def test_transition_created_to_running(self, mission):
        mission.set_status("initializing")
        assert mission.status == "initializing"

    def test_valid_lifecycle(self, mission):
        """Walk through a valid created → initializing → scoping → planning → executing → completed lifecycle."""
        for status in ("initializing", "scoping", "planning", "executing", "completed"):
            mission.set_status(status)
            assert mission.status == status

    def test_invalid_transition_sets_raw_status(self, mission):
        """Invalid FSM transition still sets raw status but logs a warning."""
        # created → completed is not a valid FSM transition
        mission.set_status("completed")
        assert mission.status == "completed"

    def test_pause_and_resume(self, mission):
        mission.set_status("initializing")
        mission.set_status("scoping")
        mission.set_status("planning")
        mission.set_status("executing")
        mission.pause()
        assert mission.status == "paused"
        mission.resume()
        assert mission.status == "running"

    def test_stop_sets_stopping(self, mission):
        mission.stop()
        assert mission.status == "stopping"
        assert mission.is_stopped()


class TestMissionBlackboard:
    def test_blackboard_exists(self, mission):
        assert mission.blackboard is not None

    def test_blackboard_read_all_returns_dict(self, mission):
        result = mission.blackboard.read_all()
        assert isinstance(result, dict)


class TestAttackSurface:
    def test_add_service(self, mission):
        svc = mission.add_service("10.0.0.1", 80, service="http")
        assert svc.host == "10.0.0.1"
        assert svc.port == 80
        assert len(mission.attack_surface.services) == 1

    def test_add_vulnerability(self, mission):
        vuln = mission.add_vulnerability("V-1", "SQL Injection", "high", cve_id="CVE-2024-0001")
        assert vuln.title == "SQL Injection"
        assert len(mission.attack_surface.vulnerabilities) == 1

    def test_add_webapp(self, mission):
        app = mission.add_webapp("https://example.com", technologies=["nginx"])
        assert app.url == "https://example.com"
        assert len(mission.attack_surface.web_apps) == 1


class TestCredentialStore:
    def test_add_and_retrieve_credential(self, mission):
        cred = Credential(
            username="admin",
            password="secret",
            service="ssh",
            host="10.0.0.1",
        )
        mission.credential_store.add(cred)
        assert mission.credential_store.count == 1

    def test_get_for_service(self, mission):
        cred = Credential(username="root", password="toor", service="ssh", host="10.0.0.1")
        mission.credential_store.add(cred)
        results = mission.credential_store.get_for_service("ssh")
        assert len(results) == 1
        assert results[0].username == "root"

    def test_duplicate_credential_not_added(self, mission):
        cred = Credential(username="admin", password="pass", service="ftp", host="10.0.0.1")
        mission.credential_store.add(cred)
        mission.credential_store.add(cred)
        assert mission.credential_store.count == 1


class TestMissionRepr:
    def test_to_dict(self, mission):
        d = mission.to_dict()
        assert d["target"] == "10.0.0.1"
        assert d["directive"] == "Test scan"
        assert d["status"] == "created"
        assert "id" in d

    def test_id_is_uuid_format(self, mission):
        parts = mission.id.split("-")
        assert len(parts) == 5  # Standard UUID


class TestFindingDedup:
    def test_add_duplicate_finding_increments_count(self, mission):
        finding = {"template-id": "CVE-1", "host": "10.0.0.1", "port": 80, "name": "vuln"}
        mission.add_finding(dict(finding))
        mission.add_finding(dict(finding))
        assert len(mission.findings) == 1
        assert mission.findings[0]["count"] == 2
