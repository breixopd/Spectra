"""Perceptor layer — parsers that convert tool output into structured facts.

Format-based, not tool-specific. Each parser handles a specific output format
(XML, JSON, plaintext) and extracts typed facts for the planner.

Parsers are pluggable — register new format handlers without touching existing code.
"""

from spectra_mission.perceptors.fact_types import (
    DiscoveredHost,
    DiscoveredPort,
    DiscoveredService,
    DiscoveredVulnerability,
    ExploitResult,
)
from spectra_mission.perceptors.json_parser import JsonPerceptor
from spectra_mission.perceptors.text_parser import TextPerceptor
from spectra_mission.perceptors.xml_parser import XmlPerceptor

__all__ = [
    "DiscoveredHost",
    "DiscoveredPort",
    "DiscoveredService",
    "DiscoveredVulnerability",
    "ExploitResult",
    "JsonPerceptor",
    "TextPerceptor",
    "XmlPerceptor",
]
