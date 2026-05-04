"""Tests for the wordlists service."""

from spectra_platform.services.ai.wordlists import generate_credential_list


class TestGenerateCredentialList:
    def test_ssh_credentials(self):
        creds = generate_credential_list("ssh")
        assert "root" in creds["users"]
        assert "admin" in creds["users"]
        assert len(creds["passwords"]) > 0

    def test_ftp_credentials(self):
        creds = generate_credential_list("ftp")
        assert "anonymous" in creds["users"]
        assert "" in creds["passwords"]  # Anonymous has blank password

    def test_mysql_credentials(self):
        creds = generate_credential_list("mysql")
        assert "root" in creds["users"]

    def test_unknown_service_defaults_to_http(self):
        creds = generate_credential_list("unknown_service")
        http_creds = generate_credential_list("http")
        assert creds == http_creds

    def test_case_insensitive(self):
        creds = generate_credential_list("SSH")
        assert "root" in creds["users"]

    def test_product_enrichment_tomcat(self):
        creds = generate_credential_list("http", product="Apache Tomcat")
        assert "tomcat" in creds["users"]
        assert "s3cret" in creds["passwords"]

    def test_product_enrichment_jenkins(self):
        creds = generate_credential_list("http", product="Jenkins 2.0")
        assert "admin" in creds["users"]
        assert "jenkins" in creds["passwords"]

    def test_product_enrichment_wordpress(self):
        creds = generate_credential_list("http", product="WordPress 5.8")
        assert "wp-admin" in creds["users"]

    def test_no_product_no_enrichment(self):
        creds = generate_credential_list("ssh", product=None)
        assert "tomcat" not in creds["users"]

    def test_redis_empty_user(self):
        creds = generate_credential_list("redis")
        assert "" in creds["users"]
        assert "foobared" in creds["passwords"]

    def test_rdp_has_passwords(self):
        creds = generate_credential_list("rdp")
        assert "administrator" in creds["users"]
        assert "P@ssw0rd" in creds["passwords"]

    def test_returns_dict_with_users_and_passwords(self):
        creds = generate_credential_list("smb")
        assert "users" in creds
        assert "passwords" in creds
        assert isinstance(creds["users"], list)
        assert isinstance(creds["passwords"], list)
