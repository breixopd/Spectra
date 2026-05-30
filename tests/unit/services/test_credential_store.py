"""Unit tests for CredentialStore and credential extraction."""

from spectra_mission.credentials import (
    MAX_CREDENTIALS_PER_MISSION,
    Credential,
    CredentialStore,
    extract_credentials_from_output,
)


class TestCredential:
    def test_defaults(self):
        c = Credential(username="admin", password="pass", service="ssh", host="10.0.0.1")
        assert c.credential_type == "password"
        assert c.verified is False
        assert c.port is None
        assert c.source == ""
        assert c.timestamp  # non-empty


class TestCredentialStore:
    def test_add_and_get_all(self):
        store = CredentialStore()
        c = Credential(username="root", password="toor", service="ssh", host="10.0.0.1")
        store.add(c)
        assert store.count == 1
        assert store.get_all() == [c]

    def test_deduplication(self):
        store = CredentialStore()
        c1 = Credential(username="admin", password="pass", service="http", host="10.0.0.1")
        c2 = Credential(username="admin", password="pass", service="http", host="10.0.0.1")
        store.add(c1)
        store.add(c2)
        assert store.count == 1

    def test_duplicate_upgrades_verified(self):
        store = CredentialStore()
        c1 = Credential(username="admin", password="pass", service="ssh", host="10.0.0.1", verified=False)
        c2 = Credential(username="admin", password="pass", service="ssh", host="10.0.0.1", verified=True)
        store.add(c1)
        store.add(c2)
        assert store.count == 1
        assert store.get_all()[0].verified is True

    def test_different_services_not_deduped(self):
        store = CredentialStore()
        store.add(Credential(username="admin", password="pass", service="ssh", host="10.0.0.1"))
        store.add(Credential(username="admin", password="pass", service="ftp", host="10.0.0.1"))
        assert store.count == 2

    def test_get_for_service(self):
        store = CredentialStore()
        store.add(Credential(username="a", password="b", service="ssh", host="10.0.0.1"))
        store.add(Credential(username="c", password="d", service="http", host="10.0.0.1"))
        store.add(Credential(username="e", password="f", service="ssh", host="10.0.0.2"))
        assert len(store.get_for_service("ssh")) == 2
        assert len(store.get_for_service("ssh", host="10.0.0.1")) == 1

    def test_get_for_host(self):
        store = CredentialStore()
        store.add(Credential(username="a", password="b", service="ssh", host="10.0.0.1"))
        store.add(Credential(username="c", password="d", service="http", host="10.0.0.2"))
        assert len(store.get_for_host("10.0.0.1")) == 1
        assert len(store.get_for_host("10.0.0.3")) == 0

    def test_max_capacity(self):
        store = CredentialStore()
        for i in range(MAX_CREDENTIALS_PER_MISSION + 5):
            store.add(Credential(username=f"user{i}", password="p", service="ssh", host="h"))
        assert store.count == MAX_CREDENTIALS_PER_MISSION

    def test_get_summary_for_prompt_empty(self):
        store = CredentialStore()
        assert store.get_summary_for_prompt() == ""

    def test_get_summary_for_prompt(self):
        store = CredentialStore()
        store.add(
            Credential(
                username="admin", password="secret", service="ssh", host="10.0.0.1", source="hydra", verified=True
            )
        )
        summary = store.get_summary_for_prompt()
        assert "admin:secret" in summary
        assert "verified" in summary
        assert "ssh@10.0.0.1" in summary

    def test_get_summary_caps_at_10(self):
        store = CredentialStore()
        for i in range(15):
            store.add(Credential(username=f"u{i}", password="p", service="ssh", host=f"h{i}"))
        summary = store.get_summary_for_prompt()
        assert "and 5 more" in summary

    def test_to_dicts(self):
        store = CredentialStore()
        store.add(Credential(username="a", password="b", service="ssh", host="h", port=22, source="test"))
        dicts = store.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["username"] == "a"
        assert dicts[0]["port"] == 22
        assert "timestamp" not in dicts[0]


class TestExtractCredentials:
    def test_hydra_output(self):
        output = (
            "[22][ssh] host: 10.0.0.1   login: admin   password: P@ssw0rd\n"
            "[22][ssh] host: 10.0.0.1   login: root   password: toor\n"
        )
        creds = extract_credentials_from_output(output, "hydra", "10.0.0.1", "ssh")
        assert len(creds) == 2
        assert creds[0].username == "admin"
        assert creds[0].password == "P@ssw0rd"
        assert creds[0].service == "ssh"
        assert creds[0].port == 22
        assert creds[0].verified is True

    def test_generic_pattern(self):
        output = "Found config: username=dbadmin password=s3cret123"
        creds = extract_credentials_from_output(output, "dirsearch", "10.0.0.1", "http")
        assert len(creds) == 1
        assert creds[0].username == "dbadmin"
        assert creds[0].password == "s3cret123"
        assert creds[0].verified is False

    def test_no_credentials(self):
        output = "Scan complete. No vulnerabilities found."
        creds = extract_credentials_from_output(output, "nmap", "10.0.0.1")
        assert creds == []
