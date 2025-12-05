import pytest
from unittest.mock import MagicMock
from app.services.mission.executor.analysis import (
    check_exploit_success,
    detect_blocking,
    suggest_retry,
    analyze_unexpected_output
)

class TestAnalysis:
    
    def test_check_exploit_success_true(self):
        outputs = [
            "uid=0(root) gid=0(root)",
            "Active Meterpreter session 1 opened",
            "[+] SQL injection found",
            "Root@Server#",
            "Administrator login successful"
        ]
        for output in outputs:
            assert check_exploit_success(output), f"Failed for {output}"

    def test_check_exploit_success_false(self):
        outputs = [
            "Attempting to exploit...",
            "Exploit failed",
            "Connection refused",
            "uid not found"
        ]
        for output in outputs:
            assert not check_exploit_success(output), f"Failed for {output}"

    def test_detect_blocking(self):
        assert detect_blocking("Connection timed out") == "timeout"
        assert detect_blocking("Connection refused") == "firewall"
        assert detect_blocking("403 Forbidden") == "waf"
        assert detect_blocking("Malware detected") == "av"
        assert detect_blocking("Connection reset by peer") == "connection_reset"
        assert detect_blocking("No route to host") == "network"
        assert detect_blocking("Permission denied") == "permission"
        assert detect_blocking("Authentication required") == "auth_required"
        assert detect_blocking("Unknown error") is None

    def test_suggest_retry_timeout(self):
        result = MagicMock(stdout="", stderr="Connection timed out")
        vector = MagicMock()
        assert suggest_retry(result, vector) == "Increase timeout or try slower scan rate"

    def test_suggest_retry_rate_limit(self):
        result = MagicMock(stdout="", stderr="429 Too Many Requests")
        vector = MagicMock()
        assert suggest_retry(result, vector) == "Add delay between requests or reduce concurrency"

    def test_suggest_retry_auth(self):
        result = MagicMock(stdout="", stderr="401 Unauthorized")
        vector = MagicMock()
        assert suggest_retry(result, vector) == "Credentials needed, try default creds or brute force"

    def test_suggest_retry_payloads(self):
        result = MagicMock(stdout="", stderr="Exploit failed")
        vector = MagicMock()
        vector.payloads = ["p1", "p2", "p3"]
        vector.attempts = ["a1"] # 1 attempt made
        # remaining = 3 - 1 - 1 = 1
        suggestion = suggest_retry(result, vector)
        assert "Try different payload" in suggestion
        assert "1 remaining" in suggestion

    def test_suggest_retry_attempts(self):
        result = MagicMock(stdout="", stderr="Exploit failed")
        vector = MagicMock()
        vector.payloads = []
        vector.attempts = ["a1"]
        vector.max_attempts = 3
        
        # 1 attempt:
        suggestion = suggest_retry(result, vector)
        assert "First attempt failed" in suggestion
        
        # 2 attempts:
        vector.attempts = ["a1", "a2"]
        suggestion = suggest_retry(result, vector)
        assert "Retry with modified approach" in suggestion
        assert "1 attempts remaining" in suggestion

    def test_analyze_unexpected_output_errors(self):
        analysis = analyze_unexpected_output("", "Connection refused")
        assert analysis["has_errors"]
        assert analysis["error_type"] == "service_down"
        
        analysis = analyze_unexpected_output("", "Rate limit exceeded")
        assert analysis["has_errors"]
        assert analysis["error_type"] == "rate_limited"
        assert "Add delay" in analysis["suggestions"][0]

    def test_analyze_unexpected_output_findings(self):
        stdout = "Server: Apache/2.4.41 (Ubuntu)"
        analysis = analyze_unexpected_output(stdout, "")
        # Regex captures only first token
        assert "server: apache/2.4.41" in analysis["interesting_findings"]

