"""Text format perceptor — parses plaintext tool output into structured facts.

Handles command-line tool output that isn't XML/JSON. Uses pattern matching
and heuristic extraction for common output formats.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from spectra_platform.services.mission.perceptors.fact_types import (
    DiscoveredHost,
    DiscoveredPort,
    DiscoveredService,
    ExploitResult,
)

logger = logging.getLogger(__name__)

# Common patterns in text-based tool output
PORT_LINE_PATTERN = re.compile(
    r"(?P<port>\d+)/(?P<proto>tcp|udp)\s+(?P<state>open|closed|filtered)\s+(?P<service>\S+)",
    re.IGNORECASE,
)

SHELL_PATTERN = re.compile(
    r"(root|www-data|apache|nginx|Administrator)\@.*[$#]",
    re.IGNORECASE,
)

METERPRETER_PATTERN = re.compile(
    r"meterpreter\s*>",
    re.IGNORECASE,
)

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

CREDENTIAL_PATTERNS = [
    re.compile(r"(?P<user>\S+):(?P<pass>\S+)", re.IGNORECASE),
    re.compile(r"Username:\s*(?P<user>\S+)", re.IGNORECASE),
    re.compile(r"Password:\s*(?P<pass>\S+)", re.IGNORECASE),
]


class TextPerceptor:
    """Parses plaintext tool output into structured discovery facts.

    Uses regex patterns and heuristics to extract meaningful data from
    command-line tool output. Handles common formats from tools like
    crackmapexec, impacket, linpeas, etc.
    """

    def parse(self, raw_output: str, source_tool: str = "") -> list[Any]:
        """Parse text output into typed facts.

        Returns:
            List of typed fact objects (DiscoveredPort, ExploitResult, etc.)
        """
        facts: list[Any] = []

        # ── Port/Service discovery (e.g., netstat, ss output) ─────────
        for match in PORT_LINE_PATTERN.finditer(raw_output):
            facts.append(DiscoveredPort(
                host_ip="",
                port=int(match.group("port")),
                protocol=match.group("proto"),
                state=match.group("state"),
                service_name=match.group("service"),
                source_tool=source_tool,
            ))

        # ── Shell access detection ─────────────────────────────────────
        if SHELL_PATTERN.search(raw_output) or METERPRETER_PATTERN.search(raw_output):
            shell_type = "meterpreter" if METERPRETER_PATTERN.search(raw_output) else "interactive_shell"
            facts.append(ExploitResult(
                host_ip=self._extract_first_ip(raw_output),
                success=True,
                shell_type=shell_type,
                evidence=raw_output[:500],
                source_tool=source_tool,
            ))

        # ── Credential extraction ──────────────────────────────────────
        creds: dict[str, str] = {}
        for pattern in CREDENTIAL_PATTERNS:
            m = pattern.search(raw_output)
            if m:
                if "user" in m.groupdict() and m.group("user"):
                    creds["user"] = m.group("user")
                if "pass" in m.groupdict() and m.group("pass"):
                    creds["pass"] = m.group("pass")

        if creds:
            facts.append(ExploitResult(
                host_ip=self._extract_first_ip(raw_output),
                success=True,
                credentials=creds,
                evidence="Credentials found in output",
                source_tool=source_tool,
            ))

        # ── IP extraction ──────────────────────────────────────────────
        ips = set(IP_PATTERN.findall(raw_output))
        for ip in ips:
            if not ip.startswith("0.") and not ip.startswith("127."):
                facts.append(DiscoveredHost(
                    ip=ip,
                    source_tool=source_tool,
                ))

        return facts

    def _extract_first_ip(self, text: str) -> str:
        """Extract the first non-localhost IP from text."""
        matches = IP_PATTERN.findall(text)
        for ip in matches:
            if not ip.startswith("0.") and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        return ""
