"""Unit tests for target input validation and SSRF prevention (app/api/schemas/mission.py)."""

from __future__ import annotations

import pytest

from app.api.schemas.mission import (
    is_internal_ip,
    is_internal_network,
    validate_target_format,
)


class TestIsInternalIp:
    def test_loopback(self):
        assert is_internal_ip("127.0.0.1") is True

    def test_private_10_range(self):
        assert is_internal_ip("10.0.0.1") is True

    def test_private_172_range(self):
        assert is_internal_ip("172.16.0.1") is True

    def test_private_192_range(self):
        assert is_internal_ip("192.168.1.1") is True

    def test_link_local(self):
        assert is_internal_ip("169.254.1.1") is True

    def test_ipv6_loopback(self):
        assert is_internal_ip("::1") is True

    def test_public_ip_not_internal(self):
        assert is_internal_ip("8.8.8.8") is False

    def test_public_ip_93(self):
        assert is_internal_ip("93.184.216.34") is False

    def test_invalid_string_returns_false(self):
        assert is_internal_ip("not-an-ip") is False

    def test_empty_returns_false(self):
        assert is_internal_ip("") is False


class TestIsInternalNetwork:
    def test_private_cidr(self):
        assert is_internal_network("10.0.0.0/8") is True

    def test_overlapping_cidr(self):
        assert is_internal_network("192.168.0.0/24") is True

    def test_public_cidr(self):
        assert is_internal_network("8.8.8.0/24") is False

    def test_invalid_cidr_returns_false(self):
        assert is_internal_network("not-a-cidr") is False


class TestValidateTargetFormat:
    def test_valid_ip(self):
        result = validate_target_format("93.184.216.34")
        assert result == "93.184.216.34"

    def test_valid_domain(self):
        result = validate_target_format("example.com")
        assert result == "example.com"

    def test_valid_subdomain(self):
        result = validate_target_format("sub.example.com")
        assert result == "sub.example.com"

    def test_valid_cidr(self):
        result = validate_target_format("10.0.0.0/24")
        assert result == "10.0.0.0/24"

    def test_valid_url(self):
        result = validate_target_format("https://example.com/path")
        assert result == "https://example.com/path"

    def test_ip_with_port(self):
        result = validate_target_format("93.184.216.34:8080")
        assert result == "93.184.216.34:8080"

    def test_empty_target_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_target_format("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_target_format("   ")

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid"):
            validate_target_format("!!!invalid!!!")

    def test_invalid_ip_rejected(self):
        with pytest.raises(ValueError, match="Invalid IP"):
            validate_target_format("999.999.999.999")

    def test_url_without_host_rejected(self):
        with pytest.raises(ValueError, match="Invalid"):
            validate_target_format("http://")

    def test_strips_whitespace(self):
        result = validate_target_format("  example.com  ")
        assert result == "example.com"
