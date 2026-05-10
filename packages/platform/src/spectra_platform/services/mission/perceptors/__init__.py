"""Perceptor layer — parsers that convert tool output into structured facts.

Format-based, not tool-specific. Each parser handles a specific output format
(XML, JSON, plaintext) and extracts typed facts for the planner.

Parsers are pluggable — register new format handlers without touching existing code.
"""

from spectra_platform.services.mission.perceptors.xml_parser import XmlPerceptor
from spectra_platform.services.mission.perceptors.json_parser import JsonPerceptor
from spectra_platform.services.mission.perceptors.text_parser import TextPerceptor
from spectra_platform.services.mission.perceptors.fact_types import (
    DiscoveredHost,
    DiscoveredPort,
    DiscoveredService,
    DiscoveredVulnerability,
    ExploitResult,
)

__all__ = [
    "XmlPerceptor",
    "JsonPerceptor",
    "TextPerceptor",
    "DiscoveredHost",
    "DiscoveredPort",
    "DiscoveredService",
    "DiscoveredVulnerability",
    "ExploitResult",
]
