"""Tests for the MITRE ATT&CK mapping service."""

from app.services.ai.mitre_attack import (
    TECHNIQUE_MAP,
    tag_finding_with_attack,
    generate_navigator_json,
    get_attack_summary,
    _resolve_techniques,
)


class TestTechniqueMap:
    """Verify the TECHNIQUE_MAP covers expected tools."""

    def test_nmap_mapped(self):
        assert ("nmap", "*") in TECHNIQUE_MAP
        assert "T1046" in TECHNIQUE_MAP[("nmap", "*")]

    def test_nuclei_mapped(self):
        assert ("nuclei", "*") in TECHNIQUE_MAP
        assert "T1595.002" in TECHNIQUE_MAP[("nuclei", "*")]

    def test_gobuster_mapped(self):
        assert ("gobuster", "*") in TECHNIQUE_MAP
        assert "T1083" in TECHNIQUE_MAP[("gobuster", "*")]

    def test_ffuf_mapped(self):
        assert ("ffuf", "*") in TECHNIQUE_MAP
        assert "T1083" in TECHNIQUE_MAP[("ffuf", "*")]

    def test_hydra_mapped(self):
        assert ("hydra", "*") in TECHNIQUE_MAP
        assert "T1110.001" in TECHNIQUE_MAP[("hydra", "*")]

    def test_sqlmap_mapped(self):
        assert ("sqlmap", "*") in TECHNIQUE_MAP
        assert "T1190" in TECHNIQUE_MAP[("sqlmap", "*")]

    def test_searchsploit_mapped(self):
        assert ("searchsploit", "*") in TECHNIQUE_MAP
        assert "T1588.005" in TECHNIQUE_MAP[("searchsploit", "*")]

    def test_metasploit_mapped(self):
        assert ("metasploit", "*") in TECHNIQUE_MAP
        assert "T1203" in TECHNIQUE_MAP[("metasploit", "*")]

    def test_nikto_mapped(self):
        assert ("nikto", "*") in TECHNIQUE_MAP
        assert "T1595.002" in TECHNIQUE_MAP[("nikto", "*")]

    def test_wpscan_mapped(self):
        assert ("wpscan", "*") in TECHNIQUE_MAP
        assert "T1595.002" in TECHNIQUE_MAP[("wpscan", "*")]

    def test_credential_dumping_mapped(self):
        assert ("credential_dumping", "*") in TECHNIQUE_MAP
        assert "T1003" in TECHNIQUE_MAP[("credential_dumping", "*")]

    def test_privilege_escalation_mapped(self):
        assert ("privilege_escalation", "*") in TECHNIQUE_MAP
        assert "T1068" in TECHNIQUE_MAP[("privilege_escalation", "*")]

    def test_lateral_movement_mapped(self):
        assert ("lateral_movement", "*") in TECHNIQUE_MAP
        assert "T1021" in TECHNIQUE_MAP[("lateral_movement", "*")]

    def test_data_exfiltration_mapped(self):
        assert ("data_exfiltration", "*") in TECHNIQUE_MAP
        assert "T1041" in TECHNIQUE_MAP[("data_exfiltration", "*")]


class TestResolveTechniques:
    """Test the internal technique resolution logic."""

    def test_specific_action_preferred(self):
        result = _resolve_techniques("nmap", "scan")
        assert result == ["T1046"]

    def test_wildcard_fallback(self):
        result = _resolve_techniques("nmap", "unknown_action")
        assert result == ["T1046"]

    def test_unknown_tool_returns_empty(self):
        assert _resolve_techniques("unknown_tool", "scan") == []

    def test_case_insensitive(self):
        assert _resolve_techniques("NMAP", "SCAN") == ["T1046"]

    def test_whitespace_stripped(self):
        assert _resolve_techniques("  nmap  ", "  scan  ") == ["T1046"]


class TestTagFindingWithAttack:
    """Test tag_finding_with_attack function."""

    def test_tags_nmap_finding(self):
        finding = {"tool_id": "nmap", "host": "10.0.0.1", "port": 80}
        result = tag_finding_with_attack(finding)
        assert "mitre_techniques" in result
        assert len(result["mitre_techniques"]) == 1
        assert result["mitre_techniques"][0]["id"] == "T1046"
        assert result["mitre_techniques"][0]["name"] == "Network Service Discovery"

    def test_tags_nuclei_finding(self):
        finding = {"tool": "nuclei", "template-id": "cve-2021-1234"}
        result = tag_finding_with_attack(finding)
        assert result["mitre_techniques"][0]["id"] == "T1595.002"

    def test_uses_source_field(self):
        finding = {"source": "hydra", "type": "brute_force"}
        result = tag_finding_with_attack(finding)
        assert result["mitre_techniques"][0]["id"] == "T1110.001"

    def test_unknown_tool_returns_empty_list(self):
        finding = {"tool_id": "unknown"}
        result = tag_finding_with_attack(finding)
        assert result["mitre_techniques"] == []

    def test_does_not_mutate_original(self):
        original = {"tool_id": "nmap", "host": "10.0.0.1"}
        result = tag_finding_with_attack(original)
        assert "mitre_techniques" not in original
        assert "mitre_techniques" in result

    def test_preserves_existing_fields(self):
        finding = {"tool_id": "nmap", "extra_data": "keep_this"}
        result = tag_finding_with_attack(finding)
        assert result["extra_data"] == "keep_this"

    def test_empty_finding(self):
        result = tag_finding_with_attack({})
        assert result["mitre_techniques"] == []


class TestGenerateNavigatorJson:
    """Test generate_navigator_json function."""

    def test_generates_valid_structure(self):
        findings = [
            {"tool_id": "nmap", "host": "10.0.0.1"},
            {"tool_id": "nuclei", "template-id": "test"},
        ]
        result = generate_navigator_json(findings)

        assert result["name"] == "Spectra Mission Findings"
        assert result["domain"] == "enterprise-attack"
        assert "versions" in result
        assert "techniques" in result
        assert "gradient" in result

    def test_technique_scores(self):
        findings = [
            {"tool_id": "nmap", "host": "10.0.0.1"},
            {"tool_id": "nmap", "host": "10.0.0.2"},
            {"tool_id": "nuclei", "template-id": "test"},
        ]
        result = generate_navigator_json(findings)
        techniques = {t["techniqueID"]: t for t in result["techniques"]}

        assert techniques["T1046"]["score"] == 2
        assert techniques["T1595.002"]["score"] == 1

    def test_empty_findings(self):
        result = generate_navigator_json([])
        assert result["techniques"] == []
        assert result["gradient"]["maxValue"] == 1

    def test_unknown_tools_excluded(self):
        findings = [{"tool_id": "unknown_tool"}]
        result = generate_navigator_json(findings)
        assert result["techniques"] == []

    def test_navigator_version_fields(self):
        result = generate_navigator_json([{"tool_id": "nmap"}])
        assert "attack" in result["versions"]
        assert "navigator" in result["versions"]
        assert "layer" in result["versions"]


class TestGetAttackSummary:
    """Test get_attack_summary function."""

    def test_tactic_counts(self):
        findings = [
            {"tool_id": "nmap"},
            {"tool_id": "nuclei"},
            {"tool_id": "hydra"},
        ]
        result = get_attack_summary(findings)

        assert result["total_techniques"] == 3
        assert result["total_findings_mapped"] == 3
        assert "TA0007" in result["tactics"]  # Discovery (nmap)
        assert "TA0043" in result["tactics"]  # Reconnaissance (nuclei)
        assert "TA0006" in result["tactics"]  # Credential Access (hydra)

    def test_tactic_names_included(self):
        findings = [{"tool_id": "nmap"}]
        result = get_attack_summary(findings)
        assert result["tactic_names"]["TA0007"] == "Discovery"

    def test_empty_findings(self):
        result = get_attack_summary([])
        assert result["total_techniques"] == 0
        assert result["total_findings_mapped"] == 0
        assert result["tactics"] == {}

    def test_unmapped_findings_not_counted(self):
        findings = [
            {"tool_id": "nmap"},
            {"tool_id": "unknown_tool"},
        ]
        result = get_attack_summary(findings)
        assert result["total_findings_mapped"] == 1

    def test_multiple_same_tool(self):
        findings = [
            {"tool_id": "nmap", "host": "a"},
            {"tool_id": "nmap", "host": "b"},
        ]
        result = get_attack_summary(findings)
        assert result["tactics"]["TA0007"] == 2
        assert result["total_techniques"] == 1
