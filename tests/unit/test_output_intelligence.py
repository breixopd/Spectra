"""Tests for output intelligence extraction."""


from app.services.ai.output_intelligence import ExtractedIntel, extract_intelligence


class TestExtractedIntelDataclass:
    def test_creation(self):
        intel = ExtractedIntel("credential", "admin:pass", 0.95, "hydra", "raw match")
        assert intel.type == "credential"
        assert intel.value == "admin:pass"
        assert intel.confidence == 0.95


class TestExtractCredentials:
    def test_hydra_login_password(self):
        output = "[22][ssh] host: 10.0.0.1   login: admin   password: secret123"
        intel = extract_intelligence("hydra", output)
        creds = [i for i in intel if i.type == "credential"]
        assert len(creds) >= 1
        assert "admin:secret123" in creds[0].value

    def test_ntlm_hash(self):
        output = "Administrator:500:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0"
        intel = extract_intelligence("secretsdump", output)
        creds = [i for i in intel if i.type == "credential"]
        assert len(creds) >= 1
        assert "Administrator" in creds[0].value

    def test_private_key_detection(self):
        output = "Found file: id_rsa\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK..."
        intel = extract_intelligence("linpeas", output)
        creds = [i for i in intel if i.type == "credential"]
        assert any(c.value == "private_key_found" for c in creds)


class TestExtractHosts:
    def test_ip_addresses(self):
        output = "Discovered host: 192.168.1.50\nAlso found 10.0.0.5"
        intel = extract_intelligence("nmap", output)
        hosts = [i for i in intel if i.type == "host"]
        ips = [h.value for h in hosts if "." in h.value and h.value[0].isdigit()]
        assert "192.168.1.50" in ips
        assert "10.0.0.5" in ips

    def test_skip_loopback_ips(self):
        output = "127.0.0.1 localhost\n255.255.255.255 broadcast\n0.0.0.0"
        intel = extract_intelligence("nmap", output)
        hosts = [i for i in intel if i.type == "host"]
        host_values = [h.value for h in hosts]
        assert "127.0.0.1" not in host_values
        assert "255.255.255.255" not in host_values
        assert "0.0.0.0" not in host_values

    def test_subdomains(self):
        output = "Found: admin.example.com\napi.example.com"
        intel = extract_intelligence("subfinder", output)
        hosts = [i for i in intel if i.type == "host"]
        values = [h.value for h in hosts]
        assert "admin.example.com" in values

    def test_skip_file_extensions_as_subdomains(self):
        output = "script.bundle.js\nstyle.main.css"
        intel = extract_intelligence("whatweb", output)
        hosts = [i for i in intel if i.type == "host"]
        values = [h.value for h in hosts]
        assert "script.bundle.js" not in values
        assert "style.main.css" not in values


class TestExtractServices:
    def test_nmap_service_versions(self):
        output = "22/tcp   open  ssh     OpenSSH 8.9p1\n80/tcp   open  http    nginx 1.18.0"
        intel = extract_intelligence("nmap", output)
        services = [i for i in intel if i.type == "service"]
        assert len(services) == 2
        assert any("22:ssh" in s.value for s in services)
        assert any("80:http" in s.value for s in services)


class TestExtractVulnerabilities:
    def test_cve_extraction(self):
        output = "[critical] CVE-2021-44228 Apache Log4j RCE\n[high] CVE-2023-12345"
        intel = extract_intelligence("nuclei", output)
        vulns = [i for i in intel if i.type == "vulnerability"]
        cve_values = [v.value for v in vulns]
        assert "CVE-2021-44228" in cve_values
        assert "CVE-2023-12345" in cve_values

    def test_sqli_indicators(self):
        output = "SQL injection found in parameter 'id'"
        intel = extract_intelligence("sqlmap", output)
        vulns = [i for i in intel if i.type == "vulnerability"]
        assert any("sqli:" in v.value for v in vulns)


class TestExtractUsers:
    def test_email_addresses(self):
        output = "Contact: admin@example.com\nSupport: help@corp.org"
        intel = extract_intelligence("recon", output)
        users = [i for i in intel if i.type == "user"]
        emails = [u.value for u in users]
        assert "admin@example.com" in emails

    def test_linux_passwd_users(self):
        output = "customuser:x:1001:1001::/home/customuser:/bin/bash\nroot:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin"
        intel = extract_intelligence("linpeas", output)
        users = [i for i in intel if i.type == "user"]
        values = [u.value for u in users]
        assert "customuser" in values
        # System users should be filtered
        assert "root" not in values
        assert "nobody" not in values


class TestEmptyOutput:
    def test_empty_string(self):
        intel = extract_intelligence("nmap", "")
        assert intel == []

    def test_no_matches(self):
        intel = extract_intelligence("tool", "just some regular text with no patterns")
        assert intel == []
