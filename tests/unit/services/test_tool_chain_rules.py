"""Tests for tool chain rules — deterministic follow-up tool queueing."""

from spectra_platform.services.mission.tool_chain_rules import (
    CHAIN_RULES,
    ChainRule,
    get_triggered_rules,
)


class TestChainRuleDataclass:
    def test_chain_rule_defaults(self):
        rule = ChainRule("nmap", r"\d+/tcp", "nikto", {"target": "{host}"}, "desc")
        assert rule.priority == 5

    def test_chain_rule_custom_priority(self):
        rule = ChainRule("nmap", r"", "nikto", {}, "desc", priority=1)
        assert rule.priority == 1


class TestChainRulesRegistry:
    def test_chain_rules_not_empty(self):
        assert len(CHAIN_RULES) > 0

    def test_all_rules_have_required_fields(self):
        for rule in CHAIN_RULES:
            assert rule.source_tool
            assert rule.trigger_pattern
            assert rule.next_tool
            assert rule.description


class TestGetTriggeredRules:
    def test_nmap_http_triggers_whatweb(self):
        output = "80/tcp   open  http    Apache httpd 2.4.49"
        triggered = get_triggered_rules("nmap", output, "192.168.1.1")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "whatweb" in tool_names

    def test_nmap_http_triggers_multiple(self):
        output = "80/tcp   open  http"
        triggered = get_triggered_rules("nmap", output, "10.0.0.1")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "whatweb" in tool_names
        assert "nikto" in tool_names
        assert "dirsearch" in tool_names

    def test_nmap_smb_triggers_enum4linux(self):
        output = "445/tcp  open  microsoft-ds"
        triggered = get_triggered_rules("nmap", output, "10.0.0.1")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "enum4linux" in tool_names
        assert "crackmapexec" in tool_names

    def test_nmap_ssh_triggers_hydra(self):
        output = "22/tcp   open  ssh"
        triggered = get_triggered_rules("nmap", output, "10.0.0.1")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "hydra" in tool_names

    def test_whatweb_wordpress(self):
        output = "WordPress version 5.8"
        triggered = get_triggered_rules("whatweb", output, "example.com")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "wpscan" in tool_names

    def test_whatweb_apache_version(self):
        output = "Apache/2.4.49 is running"
        triggered = get_triggered_rules("whatweb", output, "target.com")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "nuclei" in tool_names

    def test_no_match_returns_empty(self):
        output = "nothing interesting"
        triggered = get_triggered_rules("nmap", output, "host")
        assert triggered == []

    def test_wrong_source_tool_returns_empty(self):
        output = "80/tcp   open  http"
        triggered = get_triggered_rules("wrong_tool", output, "host")
        assert triggered == []

    def test_results_sorted_by_priority(self):
        output = "80/tcp   open  http"
        triggered = get_triggered_rules("nmap", output, "10.0.0.1")
        priorities = [r.priority for r, _ in triggered]
        assert priorities == sorted(priorities)

    def test_host_placeholder_resolved(self):
        output = "80/tcp   open  http"
        triggered = get_triggered_rules("nmap", output, "192.168.1.100")
        for _rule, args in triggered:
            for v in args.values():
                assert "{host}" not in v
                if "192.168.1.100" in v:
                    break
            else:
                # At least the target arg should have the host
                if "target" in args:
                    assert "192.168.1.100" in args["target"]

    def test_port_placeholder_resolved(self):
        output = "8080/tcp   open  http"
        triggered = get_triggered_rules("nmap", output, "host.com")
        # whatweb gets {host}:{port}
        for rule, args in triggered:
            if rule.next_tool == "whatweb":
                assert "8080" in args.get("target", "")
                break

    def test_subfinder_triggers_httpx(self):
        output = "sub.example.com\ntest.example.com"
        triggered = get_triggered_rules("subfinder", output, "example.com")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "httpx" in tool_names

    def test_hydra_creds_triggers_crackmapexec(self):
        output = "[22][ssh] host: 10.0.0.1   login: admin   password: secret123"
        triggered = get_triggered_rules("hydra", output, "10.0.0.1")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "crackmapexec" in tool_names

    def test_nuclei_critical_triggers_searchsploit(self):
        output = "[critical] CVE-2021-44228 detected"
        triggered = get_triggered_rules("nuclei", output, "target.com")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "searchsploit" in tool_names

    def test_kerberos_triggers_kerbrute(self):
        output = "88/tcp   open  kerberos-sec"
        triggered = get_triggered_rules("nmap", output, "dc.corp.local")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "kerbrute" in tool_names

    def test_mysql_triggers_hydra(self):
        output = "3306/tcp   open  mysql"
        triggered = get_triggered_rules("nmap", output, "db.local")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "hydra" in tool_names
        for rule, args in triggered:
            if rule.next_tool == "hydra":
                assert args.get("service") == "mysql"

    def test_ftp_triggers_hydra(self):
        output = "21/tcp   open  ftp"
        triggered = get_triggered_rules("nmap", output, "ftp.local")
        tool_names = [r.next_tool for r, _ in triggered]
        assert "hydra" in tool_names
