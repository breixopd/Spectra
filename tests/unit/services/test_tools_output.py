from pathlib import Path
from unittest.mock import MagicMock, patch

from spectra_tools.output import (
    cleanup_mission_workspace,
    cleanup_output_directory,
    create_error_result,
    log_success,
    normalize_tool_name,
    prepare_output_directory,
    update_attack_surface_from_finding,
    validate_tool_name,
)


def test_normalize_tool_name():
    assert normalize_tool_name("Nmap") == "nmap"
    assert normalize_tool_name("Metasploit Framework") == "metasploit"
    assert normalize_tool_name("SQLMap") == "sqlmap"
    assert normalize_tool_name("unknown-tool") == "unknown-tool"


def test_validate_tool_name():
    assert validate_tool_name("nmap") is True
    assert validate_tool_name("nmap-7") is True
    assert validate_tool_name("7") is False
    assert validate_tool_name("nmap_7") is False
    assert validate_tool_name("") is False


@patch("spectra_tools.output.data_path")
def test_prepare_output_directory(mock_data_path, tmp_path):
    mock_data_path.side_effect = lambda *parts: tmp_path / Path(*parts)
    result = prepare_output_directory("mission-1", "run-1")
    assert result.exists()
    assert result == tmp_path / "missions" / "mission-1" / "scans" / "run-1"


@patch("spectra_tools.output.data_path")
def test_cleanup_mission_workspace(mock_data_path, tmp_path):
    workspace = tmp_path / "missions" / "mission-1"
    workspace.mkdir(parents=True)
    (workspace / "file.txt").write_text("data")
    mock_data_path.return_value = workspace

    cleanup_mission_workspace("mission-1")
    assert not workspace.exists()


def test_cleanup_output_directory_missing():
    cleanup_output_directory("/nonexistent/path")


def test_create_error_result():
    result = create_error_result("nmap", "1.2.3.4", "connection failed")
    assert result.tool_id == "nmap"
    assert result.target == "1.2.3.4"
    assert result.success is False
    assert result.exit_code == -1
    assert "connection failed" in result.stderr


def test_log_success_no_findings():
    mission = MagicMock()
    mission.log = MagicMock()

    result = MagicMock()
    result.parsed_findings = []
    result.duration_seconds = 1.5

    log_success(mission, "nmap", result)
    mission.log.assert_any_call("[OK] nmap (1.5s): scan complete, no findings")


def test_log_success_with_ports():
    mission = MagicMock()
    mission.log = MagicMock()

    result = MagicMock()
    result.parsed_findings = [
        {"port": 80, "state": "open", "service": "http"},
        {"port": 443, "state": "open", "service": "https"},
    ]
    result.duration_seconds = 2.0

    log_success(mission, "nmap", result)
    mission.log.assert_any_call("[OK] nmap (2.0s): 2 open port(s)")


def test_log_success_with_vulns():
    mission = MagicMock()
    mission.log = MagicMock()

    result = MagicMock()
    result.parsed_findings = [
        {"severity": "critical", "name": "CVE-2021-1234", "info": {"severity": "critical", "name": "Test"}},
        {"severity": "high", "name": "CVE-2021-5678"},
    ]
    result.duration_seconds = 0.0

    log_success(mission, "nuclei", result)
    mission.log.assert_any_call("[OK] nuclei: 2 vulnerability finding(s)")


def test_log_success_with_dirs():
    mission = MagicMock()
    mission.log = MagicMock()

    result = MagicMock()
    result.parsed_findings = [
        {"url": "/admin", "status": 200},
        {"url": "/login", "status": 200},
    ]
    result.duration_seconds = 0.0

    log_success(mission, "gobuster", result)
    mission.log.assert_any_call("[OK] gobuster: 2 path(s) discovered")


def test_log_success_with_creds():
    mission = MagicMock()
    mission.log = MagicMock()

    result = MagicMock()
    result.parsed_findings = [
        {"login": "admin", "password": "admin123"},
    ]
    result.duration_seconds = 0.0

    log_success(mission, "hydra", result)
    mission.log.assert_any_call("[OK] hydra: 1 credential(s) found")


def test_update_attack_surface_port():
    mission = MagicMock()
    mission.target = "1.2.3.4"

    finding = {"port": 80, "service": "http", "product": "nginx", "version": "1.18", "ip": "1.2.3.4"}
    update_attack_surface_from_finding(mission, finding)
    mission.add_service.assert_called_once_with(
        host="1.2.3.4", port=80, service="http", product="nginx", version="1.18"
    )


def test_update_attack_surface_vuln():
    mission = MagicMock()

    finding = {
        "severity": "high",
        "name": "Test Vuln",
        "template-id": "test-001",
        "info": {"classification": {"cve-id": "CVE-2021-1234"}},
    }
    update_attack_surface_from_finding(mission, finding)
    mission.add_vulnerability.assert_called_once()
    args = mission.add_vulnerability.call_args.kwargs
    assert args["title"] == "Test Vuln"
    assert args["severity"] == "high"
    assert args["cve_id"] == "CVE-2021-1234"


def test_update_attack_surface_webapp():
    mission = MagicMock()

    finding = {"url": "http://example.com", "technologies": ["PHP", "Apache"], "matcher-name": "php-detect"}
    update_attack_surface_from_finding(mission, finding)
    mission.add_webapp.assert_called_once_with(url="http://example.com", technologies=["PHP", "Apache", "php-detect"])


def test_update_attack_surface_invalid_port():
    mission = MagicMock()
    mission.target = "1.2.3.4"

    finding = {"port": "not-a-port", "service": "http"}
    update_attack_surface_from_finding(mission, finding)
    mission.add_service.assert_not_called()
