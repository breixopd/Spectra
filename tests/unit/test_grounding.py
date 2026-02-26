"""Tests for the Grounding and Anti-Hallucination Framework."""

import pytest
from app.services.ai.grounding import (
    validate_tool_output,
    extract_evidence_snippets,
    ConfidenceTracker,
    GroundedContext,
    ReasoningStep,
)


class TestToolOutputValidation:
    def test_empty_output_invalid(self):
        result = validate_tool_output("nmap", "", "")
        assert result["valid"] is False
        assert result["confidence"] == 0.0
        assert result["evidence_quality"] == "none"

    def test_nmap_valid_output(self):
        output = "Nmap scan report for 10.0.0.1\nPORT   STATE SERVICE\n22/tcp open  ssh"
        result = validate_tool_output("nmap", output, "")
        assert result["valid"] is True
        assert result["confidence"] > 0.5
        assert result["evidence_quality"] in ("strong", "weak")

    def test_nmap_xml_output(self):
        output = '<?xml version="1.0"?><nmaprun><host><address addr="10.0.0.1"/></host></nmaprun>'
        result = validate_tool_output("nmap", output, "")
        assert result["valid"] is True

    def test_nuclei_valid_output(self):
        output = "[INF] Templates: 100 | matched-at: http://example.com | template-id: cve-2021-1234"
        result = validate_tool_output("nuclei", output, "")
        assert result["valid"] is True
        assert result["confidence"] > 0.5

    def test_wrong_tool_output(self):
        result = validate_tool_output(
            "nmap", "This is just random text with no tool signatures", ""
        )
        assert result["valid"] is False
        assert result["confidence"] < 0.5

    def test_unknown_tool_weak_confidence(self):
        result = validate_tool_output("custom-scanner", "some output", "")
        assert result["valid"] is True
        assert result["confidence"] == 0.6
        assert result["evidence_quality"] == "weak"

    def test_stderr_included(self):
        result = validate_tool_output(
            "nmap", "", "Nmap scan report for 10.0.0.1\nPORT STATE SERVICE"
        )
        assert result["valid"] is True

    def test_hydra_output(self):
        output = "[DATA] attacking ssh://10.0.0.1:22/\n[22][ssh] host: 10.0.0.1   login: admin   password: secret"
        result = validate_tool_output("hydra", output, "")
        assert result["valid"] is True
        assert result["confidence"] > 0.5


class TestEvidenceExtraction:
    def test_nmap_ports(self):
        output = "22/tcp open  ssh\n80/tcp open  http\n443/tcp closed https"
        snippets = extract_evidence_snippets("nmap", output)
        assert len(snippets) >= 2
        assert any("22/tcp" in s and "open" in s for s in snippets)

    def test_nuclei_vulns(self):
        output = "[critical] CVE-2021-44228 found at http://example.com/api\n[high] XSS in search parameter"
        snippets = extract_evidence_snippets("nuclei", output)
        assert len(snippets) >= 1
        assert any("CVE-2021-44228" in s for s in snippets)

    def test_cve_extraction(self):
        output = "Found vulnerability CVE-2024-1234 in Apache 2.4.41"
        snippets = extract_evidence_snippets("nuclei", output)
        assert any("CVE-2024-1234" in s for s in snippets)

    def test_empty_output(self):
        assert extract_evidence_snippets("nmap", "") == []

    def test_max_snippets_respected(self):
        output = "\n".join(f"{i}/tcp open service{i}" for i in range(100))
        snippets = extract_evidence_snippets("nmap", output, max_snippets=3)
        assert len(snippets) <= 3

    def test_success_markers(self):
        output = "[+] Found admin panel at /admin\n[+] Discovered backup file"
        snippets = extract_evidence_snippets("gobuster", output)
        assert len(snippets) >= 1

    def test_hydra_credentials(self):
        output = "[22][ssh] host: 10.0.0.1   login: root   password: toor"
        snippets = extract_evidence_snippets("hydra", output)
        assert len(snippets) >= 1
        assert any("login:" in s for s in snippets)

    def test_http_status_codes(self):
        output = "Status: 200 [Size: 1234]\nStatus: 403 [Size: 567]"
        snippets = extract_evidence_snippets("gobuster", output)
        assert len(snippets) >= 1


class TestConfidenceTracker:
    def test_register_and_get(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 0.8)
        assert tracker.get_confidence("vuln-1") == 0.8

    def test_caps_at_one(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 1.5)
        assert tracker.get_confidence("vuln-1") == 1.0

    def test_boost_cross_verify(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 0.7)
        new = tracker.boost_confidence("vuln-1", "cross_verify")
        assert new > 0.7

    def test_boost_consensus(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 0.7)
        new = tracker.boost_confidence("vuln-1", "consensus")
        assert new > 0.7

    def test_decay(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 0.8)
        new = tracker.decay_confidence("vuln-1")
        assert new < 0.8
        assert new == 0.8 * ConfidenceTracker.FAILURE_DECAY

    def test_decay_unknown_finding(self):
        tracker = ConfidenceTracker()
        assert tracker.decay_confidence("nonexistent") == 0.0

    def test_verified_findings(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("high", 0.9)
        tracker.register_finding("low", 0.1)
        verified = tracker.get_verified_findings()
        assert "high" in verified
        assert "low" not in verified

    def test_multiple_decays(self):
        tracker = ConfidenceTracker()
        tracker.register_finding("vuln-1", 0.9)
        tracker.decay_confidence("vuln-1")
        tracker.decay_confidence("vuln-1")
        assert tracker.get_confidence("vuln-1") < 0.3


class TestGroundedContext:
    def test_empty_context_summary(self):
        ctx = GroundedContext(target="10.0.0.1", target_type="ip")
        summary = ctx.get_evidence_summary()
        assert "No evidence collected" in summary

    def test_services_in_summary(self):
        ctx = GroundedContext(
            target="10.0.0.1",
            target_type="ip",
            confirmed_services=[
                {"port": 22, "service": "ssh", "product": "OpenSSH", "version": "8.2"}
            ],
        )
        summary = ctx.get_evidence_summary()
        assert "Port 22" in summary
        assert "ssh" in summary
        assert "OpenSSH" in summary

    def test_vulns_in_summary(self):
        ctx = GroundedContext(
            target="10.0.0.1",
            target_type="ip",
            confirmed_vulns=[
                {
                    "title": "SQL Injection",
                    "severity": "high",
                    "cve_id": "CVE-2024-1234",
                }
            ],
        )
        summary = ctx.get_evidence_summary()
        assert "SQL Injection" in summary
        assert "HIGH" in summary
        assert "CVE-2024-1234" in summary

    def test_raw_evidence_in_summary(self):
        ctx = GroundedContext(
            target="10.0.0.1",
            target_type="ip",
            raw_evidence=["22/tcp open ssh OpenSSH 8.2", "80/tcp open http Apache 2.4"],
        )
        summary = ctx.get_evidence_summary()
        assert "22/tcp" in summary
        assert "RAW EVIDENCE" in summary

    def test_tool_history_in_summary(self):
        ctx = GroundedContext(
            target="10.0.0.1",
            target_type="ip",
            tools_run_with_results=[
                {"tool": "nmap", "success": True, "evidence_quality": "strong"}
            ],
        )
        summary = ctx.get_evidence_summary()
        assert "nmap" in summary
        assert "OK" in summary


class TestReasoningStep:
    def test_create(self):
        step = ReasoningStep(
            step=1,
            claim="Port 22 is running SSH",
            evidence="22/tcp open ssh OpenSSH 8.2",
            source="nmap scan output line 3",
        )
        assert step.step == 1
        assert "SSH" in step.claim
