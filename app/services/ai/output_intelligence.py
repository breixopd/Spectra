"""
Extract actionable intelligence from tool outputs using regex patterns.
Faster and cheaper than LLM analysis for common output formats.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ExtractedIntel:
    type: str  # "credential", "service", "vulnerability", "host", "file", "user"
    value: str
    confidence: float  # 0-1
    source_tool: str
    raw_match: str


def extract_intelligence(tool_id: str, output: str) -> list[ExtractedIntel]:
    """Extract structured intelligence from raw tool output."""
    intel: list[ExtractedIntel] = []

    # Credentials
    for match in re.finditer(r'login:\s*(\S+)\s+password:\s*(\S+)', output, re.I):
        intel.append(ExtractedIntel(
            "credential", f"{match.group(1)}:{match.group(2)}", 0.95, tool_id, match.group(0)))

    # NTLM hashes
    for match in re.finditer(r'(\w+):\d+:([a-fA-F0-9]{32}):([a-fA-F0-9]{32})', output):
        intel.append(ExtractedIntel(
            "credential", f"{match.group(1)}:{match.group(2)}:{match.group(3)}", 0.99, tool_id, match.group(0)))

    # IP addresses (as potential new targets)
    for match in re.finditer(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', output):
        ip = match.group(1)
        # Validate IP octets and skip loopback/broadcast
        octets = ip.split(".")
        if all(0 <= int(o) <= 255 for o in octets) and not ip.startswith(('0.', '127.', '255.')):
            intel.append(ExtractedIntel("host", ip, 0.6, tool_id, match.group(0)))

    # Subdomains
    for match in re.finditer(r'([\w-]+\.[\w-]+\.[\w]+)', output):
        domain = match.group(1)
        if not domain.endswith(('.js', '.css', '.html', '.txt')):
            intel.append(ExtractedIntel("host", domain, 0.7, tool_id, match.group(0)))

    # Service versions (nmap-style)
    for match in re.finditer(r'(\d+)/tcp\s+open\s+(\S+)\s+(.+?)$', output, re.M):
        intel.append(ExtractedIntel(
            "service", f"{match.group(1)}:{match.group(2)}:{match.group(3).strip()}", 0.95, tool_id, match.group(0)))

    # CVEs
    for match in re.finditer(r'(CVE-\d{4}-\d{4,})', output, re.I):
        intel.append(ExtractedIntel("vulnerability", match.group(1), 0.9, tool_id, match.group(0)))

    # Email addresses
    for match in re.finditer(r'([\w.+-]+@[\w-]+\.[\w.]+)', output):
        intel.append(ExtractedIntel("user", match.group(1), 0.8, tool_id, match.group(0)))

    # Usernames from Linux passwd
    _system_users = frozenset({
        'root', 'nobody', 'daemon', 'bin', 'sys', 'sync', 'games',
        'man', 'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data',
    })
    for match in re.finditer(r'^(\w+):x:\d+:\d+:', output, re.M):
        if match.group(1) not in _system_users:
            intel.append(ExtractedIntel("user", match.group(1), 0.9, tool_id, match.group(0)))

    # Private keys
    if '-----BEGIN' in output and 'PRIVATE KEY' in output:
        intel.append(ExtractedIntel("credential", "private_key_found", 1.0, tool_id, "PRIVATE KEY detected"))

    # SQL injection indicators
    for match in re.finditer(r'(sql injection|injectable|vulnerable|syntax error.*SQL)', output, re.I):
        intel.append(ExtractedIntel(
            "vulnerability", f"sqli:{match.group(0)[:50]}", 0.85, tool_id, match.group(0)))

    return intel
