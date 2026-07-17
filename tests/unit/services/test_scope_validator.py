"""Tests for deterministic scope validation."""

import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from spectra_domain.scope_validator import (
    is_target_in_scope,
    parse_scope,
    validate_command_target,
)


class TestParseScope:
    def test_parse_single_ip(self):
        networks, _domains = parse_scope(["192.168.1.1"])
        assert len(networks) == 1
        assert ipaddress.ip_address("192.168.1.1") in networks[0]

    def test_parse_cidr(self):
        networks, _domains = parse_scope(["10.0.0.0/24"])
        assert len(networks) == 1
        assert ipaddress.ip_address("10.0.0.50") in networks[0]

    def test_parse_domain(self):
        _networks, domains = parse_scope(["example.com"])
        assert "example.com" in domains

    def test_parse_mixed(self):
        networks, domains = parse_scope(["192.168.1.0/24", "example.com", "10.0.0.1"])
        assert len(networks) == 2
        assert len(domains) == 1

    def test_parse_ipv6(self):
        networks, domains = parse_scope(["2001:db8::/32"])
        assert domains == []
        assert ipaddress.ip_address("2001:db8::1") in networks[0]


class TestIsTargetInScope:
    @pytest.mark.asyncio
    async def test_ip_in_cidr(self):
        networks, domains = parse_scope(["10.0.0.0/24"])
        assert await is_target_in_scope("10.0.0.50", networks, domains) is True

    @pytest.mark.asyncio
    async def test_ip_outside_cidr(self):
        networks, domains = parse_scope(["10.0.0.0/24"])
        assert await is_target_in_scope("10.0.1.1", networks, domains) is False

    @pytest.mark.asyncio
    async def test_exact_ip_match(self):
        networks, domains = parse_scope(["192.168.1.100"])
        assert await is_target_in_scope("192.168.1.100", networks, domains) is True

    @pytest.mark.asyncio
    async def test_domain_exact_match(self):
        networks, domains = parse_scope(["example.com"])
        assert await is_target_in_scope("example.com", networks, domains) is True

    @pytest.mark.asyncio
    async def test_subdomain_match(self):
        networks, domains = parse_scope(["example.com"])
        assert await is_target_in_scope("sub.example.com", networks, domains) is True

    @pytest.mark.asyncio
    async def test_domain_no_match(self):
        networks, domains = parse_scope(["example.com"])
        assert await is_target_in_scope("evil.com", networks, domains) is False

    @pytest.mark.asyncio
    async def test_empty_target(self):
        networks, domains = parse_scope(["10.0.0.0/24"])
        assert await is_target_in_scope("", networks, domains) is False


class TestValidateCommandTarget:
    @pytest.mark.asyncio
    async def test_nmap_in_scope(self):
        ok, _reason = await validate_command_target("nmap -sV 192.168.1.1", ["192.168.1.0/24"])
        assert ok is True

    @pytest.mark.asyncio
    async def test_nmap_out_of_scope(self):
        ok, reason = await validate_command_target("nmap -sV 10.0.0.1", ["192.168.1.0/24"])
        assert ok is False
        assert "outside declared scope" in reason

    @pytest.mark.asyncio
    async def test_localhost_allowed(self):
        ok, reason = await validate_command_target("curl http://127.0.0.1", ["10.0.0.0/24"])
        assert ok is False
        assert "127.0.0.1" in reason

    @pytest.mark.asyncio
    async def test_integer_encoded_ipv4_is_not_treated_as_targetless(self):
        ok, reason = await validate_command_target("nmap 2130706433", ["10.0.0.0/24"])
        assert ok is False
        assert "127.0.0.1" in reason

    @pytest.mark.asyncio
    async def test_ipv6_loopback_is_not_treated_as_targetless(self):
        ok, reason = await validate_command_target("curl http://[::1]", ["10.0.0.0/24"])
        assert ok is False
        assert "::1" in reason

    @pytest.mark.asyncio
    async def test_ipv6_target_in_scope(self):
        ok, _reason = await validate_command_target("nmap -6 2001:db8::1", ["2001:db8::/32"])
        assert ok is True

    @pytest.mark.asyncio
    async def test_no_targets_in_command(self):
        ok, _reason = await validate_command_target("whoami", ["10.0.0.0/24"])
        assert ok is True

    @pytest.mark.asyncio
    async def test_file_extensions_not_treated_as_domains(self):
        """File names like common.txt should not trigger scope violations."""
        result, _reason = await validate_command_target(
            "ffuf -u http://172.21.0.50 -w /usr/share/seclists/common.txt -o output.json",
            ["172.21.0.50"],
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_real_domains_still_checked(self):
        """Actual domains should still be validated against scope."""
        result, reason = await validate_command_target(
            "curl http://evil.com/payload",
            ["172.21.0.50"],
        )
        assert result is False
        assert "evil.com" in reason

    @pytest.mark.asyncio
    async def test_empty_scope(self):
        ok, _reason = await validate_command_target("nmap 10.0.0.1", [])
        assert ok is False

    @pytest.mark.asyncio
    async def test_dns_resolution_in_scope(self):
        with patch("spectra_domain.scope_validator._resolve_hostname", new_callable=AsyncMock, return_value=("192.168.1.1",)):
            networks, _domains = parse_scope(["192.168.1.0/24"])
            result = await is_target_in_scope("host.local", networks, [])
            assert result is True

    @pytest.mark.asyncio
    async def test_dns_resolution_out_of_scope(self):
        with patch("spectra_domain.scope_validator._resolve_hostname", new_callable=AsyncMock, return_value=("10.0.0.1",)):
            networks, _domains = parse_scope(["192.168.1.0/24"])
            result = await is_target_in_scope("host.local", networks, [])
            assert result is False


class TestParseScopeEdgeCases:
    def test_empty_string(self):
        networks, domains = parse_scope([""])
        assert networks == []
        assert domains == []

    def test_invalid_cidr(self):
        networks, domains = parse_scope(["999.999.999.999/24"])
        assert networks == []
        assert domains == ["999.999.999.999/24"]

    def test_invalid_ip(self):
        networks, domains = parse_scope(["999.999.999.999"])
        assert networks == []
        assert domains == ["999.999.999.999"]

    def test_unknown_format(self):
        networks, domains = parse_scope(["something-weird"])
        assert networks == []
        assert domains == ["something-weird"]
