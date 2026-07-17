"""JSON format perceptor — parses JSON tool output into structured facts.

Handles any JSON-formatted tool output (nuclei, httpx, amass, etc.).
Not specific to any tool — matches on JSON structure patterns.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from spectra_mission.perceptors.fact_types import (
    DiscoveredService,
    DiscoveredVulnerability,
)

logger = logging.getLogger(__name__)


class JsonPerceptor:
    """Parses JSON tool output into structured discovery facts.

    Auto-detects the JSON structure pattern to determine which facts to extract.
    Supports nuclei, httpx, and generic JSON arrays/objects.
    """

    def parse(self, raw_output: str, source_tool: str = "") -> list[Any]:
        """Parse JSON output into typed facts.

        Returns:
            List of DiscoveredVulnerability, DiscoveredService, or other fact objects
        """
        facts: list[Any] = []

        try:
            data = _json.loads(raw_output)
        except (_json.JSONDecodeError, TypeError):
            # Try extracting JSON block from mixed output
            data = self._extract_json_block(raw_output)
            if data is None:
                return facts

        # Handle different JSON structures
        if isinstance(data, list):
            for item in data:
                facts.extend(self._parse_item(item, source_tool))
        elif isinstance(data, dict):
            facts.extend(self._parse_item(data, source_tool))

        return facts

    def _parse_item(self, item: dict[str, Any], source_tool: str) -> list[Any]:
        """Parse a single JSON item into the appropriate fact type."""
        facts: list[Any] = []

        # ── Nuclei-style vulnerability ─────────────────────────────────
        if "template-id" in item or ("info" in item and isinstance(item.get("info"), dict)):
            info = item.get("info", item)
            severity = info.get("severity", item.get("severity", "")).lower()

            facts.append(
                DiscoveredVulnerability(
                    host_ip=item.get("host", item.get("ip", "")),
                    port=item.get("port", 0),
                    vuln_id=item.get("template-id", item.get("template_id", "")),
                    name=info.get("name", item.get("name", "")),
                    description=info.get("description", ""),
                    severity=severity,
                    matched_at=item.get("matched-at", item.get("matched_at", "")),
                    evidence=item.get("extracted-results", ""),
                    remediation=info.get("remediation", ""),
                    source_tool=source_tool or "nuclei",
                    tags=info.get("tags", []),
                )
            )
            return facts

        # ── Service discovery ─────────────────────────────────────────
        if "url" in item or "host" in item:
            host = item.get("host", item.get("ip", item.get("url", "")))
            port = item.get("port", 0)

            svc = DiscoveredService(
                host_ip=host,
                port=port,
                name=item.get("service", item.get("name", "")),
                product=item.get("product", ""),
                version=item.get("version", ""),
                source_tool=source_tool,
            )
            facts.append(svc)

        return facts

    def _extract_json_block(self, text: str) -> dict | list | None:
        """Extract a JSON block from mixed text output."""
        # Try to find JSON array or object
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start >= 0 and end > start:
                try:
                    return _json.loads(text[start : end + 1])
                except (_json.JSONDecodeError, TypeError):
                    continue
        return None
