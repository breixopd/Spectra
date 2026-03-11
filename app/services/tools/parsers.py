"""Parsers for security tool XML output."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

def xml_to_dict(element: ET.Element) -> dict[str, Any]:
    """Convert an XML element's children into a dictionary.

    Attributes become top-level keys, text becomes ``_text``,
    and child elements are recursively converted.  Multiple children
    sharing the same tag are collected into a list.
    """
    result: dict[str, Any] = {}

    for child in element:
        child_dict: dict[str, Any] = dict(child.attrib)

        text = child.text
        if text is not None:
            text = text.strip()
            if text:
                child_dict["_text"] = text

        grandchildren = xml_to_dict(child)
        if grandchildren:
            child_dict.update(grandchildren)

        tag = child.tag
        if tag in result:
            existing = result[tag]
            if isinstance(existing, list):
                existing.append(child_dict)
            else:
                result[tag] = [existing, child_dict]
        else:
            result[tag] = child_dict

    return result


def parse_nmap_xml(root: ET.Element) -> list[dict[str, Any]]:
    """Parse nmap XML output and return a list of open-port findings."""
    findings: list[dict[str, Any]] = []

    for host in root.iter("host"):
        addr_elem = host.find("address")
        if addr_elem is None:
            continue
        ip = addr_elem.get("addr", "")

        for port in host.iter("port"):
            state_elem = port.find("state")
            if state_elem is None or state_elem.get("state") != "open":
                continue

            service_elem = port.find("service")
            findings.append(
                {
                    "ip": ip,
                    "portid": port.get("portid", ""),
                    "protocol": port.get("protocol", ""),
                    "state": "open",
                    "service": service_elem.get("name")
                    if service_elem is not None
                    else None,
                    "product": service_elem.get("product")
                    if service_elem is not None
                    else None,
                    "version": service_elem.get("version")
                    if service_elem is not None
                    else None,
                }
            )

    return findings
