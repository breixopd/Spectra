"""XML format perceptor — parses nmap XML output into structured facts.

Handles any XML-formatted tool output. Not specific to nmap — any tool
that produces XML with host/port/service elements will be parsed.
"""

from __future__ import annotations

import contextlib
import logging
import xml.etree.ElementTree as ET
from typing import Any

from spectra_mission.perceptors.fact_types import (
    DiscoveredHost,
    DiscoveredPort,
)

logger = logging.getLogger(__name__)


class XmlPerceptor:
    """Parses XML tool output into structured discovery facts.

    Currently handles nmap-style XML. Extensible for other XML formats
    by registering new element handlers.
    """

    def parse(self, raw_output: str, source_tool: str = "nmap") -> list[Any]:
        """Parse XML output into typed facts.

        Returns:
            List of DiscoveredHost, DiscoveredPort, and DiscoveredService objects
        """
        facts: list[Any] = []

        try:
            root = ET.fromstring(raw_output)
        except ET.ParseError as exc:
            logger.warning("XML parse error from %s: %s", source_tool, exc)
            return facts

        # Handle nmaprun structure
        for host_elem in root.findall(".//host"):
            facts.extend(self._parse_host(host_elem, source_tool))

        # If no hosts found, try direct port elements
        if not facts:
            for port_elem in root.findall(".//port"):
                facts.append(self._parse_port(port_elem, "", source_tool))

        return facts

    def _parse_host(self, host_elem: ET.Element, source_tool: str) -> list[Any]:
        """Parse a <host> element into facts."""
        facts: list[Any] = []

        # Address
        addr_elem = host_elem.find("address")
        if addr_elem is None:
            return facts
        ip = addr_elem.get("addr", "")

        # OS detection
        os_name = ""
        os_confidence = 0
        os_elem = host_elem.find(".//osmatch")
        if os_elem is not None:
            os_name = os_elem.get("name", "")
            with contextlib.suppress(ValueError, TypeError):
                os_confidence = int(float(os_elem.get("accuracy", "0")))

        # Hostnames
        hostname = ""
        for hn in host_elem.findall("hostnames/hostname"):
            hostname = hn.get("name", "")
            break

        facts.append(DiscoveredHost(
            ip=ip,
            hostname=hostname,
            os=os_name,
            os_confidence=os_confidence,
            source_tool=source_tool,
        ))

        # Ports and services
        for port_elem in host_elem.findall("ports/port"):
            if port_elem is not None:
                facts.append(self._parse_port(port_elem, ip, source_tool))

        return facts

    def _parse_port(self, port_elem: ET.Element, host_ip: str, source_tool: str) -> DiscoveredPort:
        """Parse a <port> element."""
        port_id = int(port_elem.get("portid", "0"))
        protocol = port_elem.get("protocol", "tcp")

        state_elem = port_elem.find("state")
        state = state_elem.get("state", "unknown") if state_elem is not None else "unknown"

        svc_elem = port_elem.find("service")
        svc_name = svc_elem.get("name", "") if svc_elem is not None else ""
        svc_product = svc_elem.get("product", "") if svc_elem is not None else ""
        svc_version = svc_elem.get("version", "") if svc_elem is not None else ""
        svc_extra = svc_elem.get("extrainfo", "") if svc_elem is not None else ""

        return DiscoveredPort(
            host_ip=host_ip,
            port=port_id,
            protocol=protocol,
            state=state,
            service_name=svc_name,
            service_product=svc_product,
            service_version=svc_version,
            service_extra=svc_extra,
            source_tool=source_tool,
        )
