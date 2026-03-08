"""Tests for the wordlists service."""

import pytest
from app.services.ai.wordlists import generate_tech_wordlist, generate_credential_list


class TestGenerateTechWordlist:
    def test_empty_technologies(self):
        result = generate_tech_wordlist([])
        # Should still return default paths
        assert "/robots.txt" in result
        assert "/.env" in result

    def test_wordpress_paths(self):
        result = generate_tech_wordlist(["WordPress"])
        assert "/wp-admin/" in result
        assert "/wp-login.php" in result
        assert "/xmlrpc.php" in result

    def test_node_paths(self):
        result = generate_tech_wordlist(["Node.js"])
        assert "/api/" in result
        assert "/graphql" in result

    def test_django_paths(self):
        result = generate_tech_wordlist(["Django"])
        assert "/admin/" in result
        assert "/static/" in result

    def test_apache_paths(self):
        result = generate_tech_wordlist(["Apache"])
        assert "/.htaccess" in result
        assert "/server-status" in result

    def test_multiple_techs(self):
        result = generate_tech_wordlist(["WordPress", "Apache", "MySQL"])
        assert "/wp-admin/" in result
        assert "/.htaccess" in result
        assert "/phpmyadmin/" in result

    def test_case_insensitive_matching(self):
        result = generate_tech_wordlist(["WORDPRESS"])
        assert "/wp-admin/" in result

    def test_result_sorted(self):
        result = generate_tech_wordlist(["Apache"])
        assert result == sorted(result)

    def test_no_duplicates(self):
        result = generate_tech_wordlist(["Apache", "PHP"])
        assert len(result) == len(set(result))

    def test_default_paths_always_included(self):
        defaults = ["/robots.txt", "/sitemap.xml", "/.git/", "/.env"]
        result = generate_tech_wordlist(["RandomTech"])
        for d in defaults:
            assert d in result

    def test_php_includes_config(self):
        result = generate_tech_wordlist(["PHP"])
        assert "/phpinfo.php" in result

    def test_tomcat_paths(self):
        result = generate_tech_wordlist(["Tomcat"])
        assert "/manager/html" in result

    def test_flask_paths(self):
        result = generate_tech_wordlist(["Flask"])
        assert "/console/" in result

    def test_redis_paths(self):
        result = generate_tech_wordlist(["Redis"])
        assert "/redis/" in result


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
