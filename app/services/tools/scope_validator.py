"""Deterministic scope validation for tool execution.

Validates that target IPs/hostnames fall within the mission's declared
scope using exact IP/CIDR matching.  AI-based safety checks remain as
a secondary layer.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from functools import lru_cache

logger = logging.getLogger(__name__)

# Patterns from scope agent
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CIDR_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b")
_DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")


def parse_scope(scope_targets: list[str]) -> tuple[list[ipaddress.IPv4Network | ipaddress.IPv6Network], list[str]]:
    """Parse scope targets into networks and domain patterns.

    Returns (networks, domains) where networks are IP/CIDR entries
    and domains are hostname patterns.
    """
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    domains: list[str] = []

    for target in scope_targets:
        target = target.strip()
        if not target:
            continue
        # Try CIDR
        cidr_match = _CIDR_PATTERN.search(target)
        if cidr_match:
            try:
                networks.append(ipaddress.ip_network(cidr_match.group(), strict=False))
                continue
            except ValueError:
                pass
        # Try IP
        ip_match = _IP_PATTERN.search(target)
        if ip_match:
            try:
                networks.append(ipaddress.ip_network(ip_match.group(), strict=False))
                continue
            except ValueError:
                pass
        # Try domain
        domain_match = _DOMAIN_PATTERN.search(target)
        if domain_match:
            domains.append(domain_match.group().lower())
            continue
        # Unknown format — treat as domain
        domains.append(target.lower())

    return networks, domains


def is_target_in_scope(
    target: str,
    scope_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
    scope_domains: list[str],
) -> bool:
    """Check if a target IP or hostname falls within the declared scope.

    For IPs: exact containment check against all scope CIDRs.
    For domains: exact match or subdomain match against scope domains.
    """
    target = target.strip().lower()
    if not target:
        return False

    # Check if target is an IP
    try:
        target_ip = ipaddress.ip_address(target)
        return any(target_ip in network for network in scope_networks)
    except ValueError:
        pass

    # Check if target is a domain
    for scope_domain in scope_domains:
        if target == scope_domain or target.endswith("." + scope_domain):
            return True

    # Try resolving hostname to IP and check
    try:
        resolved_ips = _resolve_hostname(target)
        for ip_str in resolved_ips:
            try:
                ip = ipaddress.ip_address(ip_str)
                if any(ip in network for network in scope_networks):
                    return True
            except ValueError:
                continue
    except (OSError, socket.gaierror):
        pass

    return False


@lru_cache(maxsize=256)
def _resolve_hostname(hostname: str) -> tuple[str, ...]:
    """Resolve hostname to IP addresses with caching."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return tuple({r[4][0] for r in results})
    except (OSError, socket.gaierror):
        return ()


def validate_command_target(
    command: str,
    scope_targets: list[str],
) -> tuple[bool, str]:
    """Validate that a tool command only targets in-scope hosts.

    Returns (is_valid, reason).
    """
    scope_networks, scope_domains = parse_scope(scope_targets)

    if not scope_networks and not scope_domains:
        return False, "No scope targets defined"

    # Extract IPs from command
    found_ips = _IP_PATTERN.findall(command)
    found_domains = _DOMAIN_PATTERN.findall(command)

    # Filter out file-like matches (e.g., common.txt, output.json, nmap_output.xml)
    _FILE_EXTENSIONS = frozenset({
        "txt", "json", "xml", "csv", "html", "log", "conf", "cfg", "ini", "yml",
        "yaml", "toml", "md", "py", "sh", "bash", "js", "ts", "go", "rs", "rb",
        "sql", "db", "bak", "tmp", "old", "gz", "zip", "tar", "png", "jpg",
    })
    found_domains = [
        d for d in found_domains
        if d.rsplit(".", 1)[-1].lower() not in _FILE_EXTENSIONS
        and "/" not in d
    ]

    targets_to_check = found_ips + found_domains
    if not targets_to_check:
        # No extractable targets in command — allow (could be a local command)
        return True, "No targets extracted from command"

    for target in targets_to_check:
        # Skip common non-target IPs
        if target in ("127.0.0.1", "0.0.0.0", "255.255.255.255"):
            continue
        if not is_target_in_scope(target, scope_networks, scope_domains):
            return False, f"Target {target} is outside declared scope"

    return True, "All targets within scope"
