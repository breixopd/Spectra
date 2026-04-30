"""
Universal Tool Output Parser.

Parses tool output using multiple strategies (in order of preference):
1. Structured formats (JSON, NDJSON, XML, CSV) with field mapping
2. Regex patterns defined in plugin config
3. LLM-based extraction for complex/unknown formats

Follows SOLID principles:
- Single Responsibility: Only handles output parsing
- Open/Closed: New formats via plugin config, not code changes
- Dependency Inversion: No tool-specific code
"""

from __future__ import annotations

import csv
import json
import logging
import re
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree as SafeET

from app.services.tools.models import OutputFormat, ToolConfig

if TYPE_CHECKING:
    from app.services.ai.llm import LLMClient

logger = logging.getLogger(__name__)


class UniversalParser:
    """
    Universal tool output parser.

    Parses any tool output using plugin-defined configuration:
    - format: json/xml/csv/ndjson/text
    - mapping: Field name translations
    - regex_patterns: Extract data from text output
    - llm_extraction: Use LLM for complex parsing
    """

    def __init__(self, config: ToolConfig, llm_client: LLMClient | None = None):
        self.config = config
        self.llm_client = llm_client

    async def parse_output(
        self,
        stdout: str,
        stderr: str,
        output_file: str | None,
    ) -> list[dict[str, Any]]:
        """Parse tool output into structured findings."""
        parsing_config = self.config.parsing

        # Collect all output sources
        outputs = self._collect_output_content(stdout, output_file)

        # Include stderr for TEXT format
        if parsing_config.capture_stderr and stderr.strip() and parsing_config.format == OutputFormat.TEXT:
            outputs.append(stderr)

        if not outputs:
            return []

        # Parse each output source
        all_findings: list[dict[str, Any]] = []
        for raw_output in outputs:
            findings = await self._parse_single_output(raw_output, parsing_config.format)
            all_findings.extend(findings)

        return all_findings

    def _collect_output_content(self, stdout: str, output_file: str | None) -> list[str]:
        """Collect content from output files and/or stdout."""
        outputs: list[str] = []
        parsing_config = self.config.parsing

        if output_file:
            output_path = Path(output_file)

            if parsing_config.output_file_pattern:
                pattern = output_path.parent / parsing_config.output_file_pattern
                for f in output_path.parent.glob(pattern.name):
                    content = self._safe_read_file(f)
                    if content:
                        outputs.append(content)
            elif output_path.exists() and output_path.is_dir():
                for f in output_path.rglob("*"):
                    if not f.is_file():
                        continue
                    content = self._safe_read_file(f)
                    if content:
                        outputs.append(content)
            elif output_path.exists():
                content = self._safe_read_file(output_path)
                if content:
                    outputs.append(content)

        # Add stdout if no file output or combining is enabled
        if (not outputs or parsing_config.combine_outputs) and stdout.strip():
            outputs.append(stdout)

        return outputs

    def _safe_read_file(self, path: Path, max_size: int = 10 * 1024 * 1024) -> str | None:
        """Safely read a file, skipping binary and large files."""
        try:
            if path.stat().st_size > max_size:
                logger.warning("Skipping large file: %s", path)
                return None

            content_bytes = path.read_bytes()
            if b"\0" in content_bytes:
                logger.warning("Skipping binary file: %s", path)
                return None

            content = content_bytes.decode("utf-8", errors="replace")
            return content.strip() if content.strip() else None
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to read file %s: %s", path, e)
            return None

    async def _parse_single_output(
        self,
        raw_output: str,
        format_type: OutputFormat,
    ) -> list[dict[str, Any]]:
        """Parse a single output string based on format."""
        if not raw_output.strip():
            return []

        parsing_config = self.config.parsing

        # Strategy 1: Structured formats
        if format_type == OutputFormat.JSON:
            return self._parse_json(raw_output)
        elif format_type == OutputFormat.NDJSON:
            return self._parse_ndjson(raw_output)
        elif format_type == OutputFormat.XML:
            return self._parse_xml(raw_output)
        elif format_type == OutputFormat.CSV:
            return self._parse_csv(raw_output)

        # Strategy 2: Text with regex patterns
        if parsing_config.regex_patterns:
            findings = self._parse_with_regex(raw_output)
            if findings:
                return findings

        # Strategy 3: LLM extraction
        if parsing_config.llm_extraction and self.llm_client:
            findings = await self._parse_with_llm(raw_output)
            if findings:
                return findings

        # Fallback: Return raw output as single finding
        return [{"raw_output": raw_output[:5000]}]

    def _parse_json(self, output: str) -> list[dict[str, Any]]:
        """Parse JSON output."""
        try:
            data = json.loads(output)
            if isinstance(data, list):
                return [self._apply_mapping(item) for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                return [self._apply_mapping(data)]
            return [{"value": data}]
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON: %s", e)
            return []

    def _parse_ndjson(self, output: str) -> list[dict[str, Any]]:
        """Parse newline-delimited JSON output."""
        findings = []
        for line in output.strip().split("\n"):
            if line.strip():
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        findings.append(self._apply_mapping(data))
                except json.JSONDecodeError:
                    continue
        return findings

    def _parse_xml(self, output: str) -> list[dict[str, Any]]:
        """Parse XML output using generic conversion."""
        try:
            root = SafeET.fromstring(output)
            return self._xml_to_findings(root)
        except ET.ParseError as e:
            logger.warning("Failed to parse XML: %s", e)
            return []

    def _xml_to_findings(self, root: ET.Element) -> list[dict[str, Any]]:
        """Convert XML to findings generically.

        Handles special cases for common security tool XML formats (nmap, etc.)
        and falls back to generic element-to-dict conversion.
        """
        findings: list[dict[str, Any]] = []

        # Special handling for nmap XML (nmaprun root)
        if root.tag == "nmaprun":
            findings = self._parse_nmap_xml(root)
            if findings:
                return [self._apply_mapping(f) for f in findings]

        # Look for common result container patterns
        result_containers = [
            "host",
            "result",
            "item",
            "finding",
            "vulnerability",
            "entry",
            "port",
        ]

        for container in result_containers:
            for elem in root.iter(container):
                finding = self._element_to_dict(elem)
                if finding:
                    findings.append(self._apply_mapping(finding))

        # If no findings from containers, convert whole tree
        if not findings:
            finding = self._element_to_dict(root)
            if finding:
                findings.append(self._apply_mapping(finding))

        return findings

    def _parse_nmap_xml(self, root: ET.Element) -> list[dict[str, Any]]:
        """Parse nmap XML output into structured findings."""
        from app.services.tools.parsers import parse_nmap_xml

        return parse_nmap_xml(root)

    def _element_to_dict(self, elem: ET.Element) -> dict[str, Any]:
        """Convert XML element to dict, flattening nested structures."""
        result: dict[str, Any] = {}

        # Add attributes
        result.update(elem.attrib)

        # Add text content
        if elem.text and elem.text.strip():
            result["_text"] = elem.text.strip()

        # Add child elements (flattened)
        for child in elem:
            child_data = self._element_to_dict(child)

            # Flatten simple children
            if len(child_data) == 1 and "_text" in child_data:
                result[child.tag] = child_data["_text"]
            elif child_data:
                if child.tag in result:
                    if not isinstance(result[child.tag], list):
                        result[child.tag] = [result[child.tag]]
                    result[child.tag].append(child_data)
                else:
                    result[child.tag] = child_data

        return result

    def _parse_csv(self, output: str) -> list[dict[str, Any]]:
        """Parse CSV output."""
        try:
            reader = csv.DictReader(StringIO(output))
            return [self._apply_mapping(dict(row)) for row in reader]
        except csv.Error as e:
            logger.warning("Failed to parse CSV: %s", e)
            return []

    def _parse_with_regex(self, output: str) -> list[dict[str, Any]]:
        """Parse text output using plugin-defined regex patterns."""
        findings: list[dict[str, Any]] = []
        patterns = self.config.parsing.regex_patterns

        for pattern_config in patterns:
            pattern = pattern_config.get("pattern")
            if not pattern:
                continue

            try:
                regex = re.compile(pattern, re.MULTILINE | re.IGNORECASE)
                for match in regex.finditer(output):
                    finding = match.groupdict()
                    # Add pattern type if specified
                    if "type" in pattern_config:
                        finding["_type"] = pattern_config["type"]
                    if finding:
                        findings.append(self._apply_mapping(finding))
            except re.error as e:
                logger.warning("Invalid regex pattern '%s': %s", pattern, e)

        return findings

    async def _parse_with_llm(self, output: str) -> list[dict[str, Any]]:
        """Use LLM to extract structured findings from text output."""
        if not self.llm_client:
            return []

        try:
            from pydantic import BaseModel

            class ExtractedFinding(BaseModel):
                """A single extracted finding."""

                type: str  # service, vulnerability, info, credential
                title: str
                description: str | None = None
                host: str | None = None
                port: int | None = None
                service: str | None = None
                severity: str | None = None
                cve_id: str | None = None
                extra: dict | None = None

            class ExtractionResult(BaseModel):
                """LLM extraction result."""

                findings: list[ExtractedFinding]

            hint = self.config.parsing.extraction_hint or "security-relevant information"

            # Truncate very long outputs
            truncated = output[:8000] if len(output) > 8000 else output

            prompt = f"""Extract structured findings from this security tool output.
Focus on extracting: {hint}

Tool: {self.config.name}
Output:
```
{truncated}
```

Extract all findings (services, vulnerabilities, credentials, etc.) as structured data."""

            result = await self.llm_client.generate_structured(
                prompt=prompt,
                response_model=ExtractionResult,
                temperature=0.1,
            )

            return [f.model_dump(exclude_none=True) for f in result.findings]

        except (ValueError, TypeError, TimeoutError, RuntimeError) as e:
            logger.warning("LLM extraction failed: %s", e)
            return []

    def _apply_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply field mapping from tool output to Spectra's format."""
        if not isinstance(data, dict):
            return {"value": data}

        mapping = self.config.parsing.mapping
        if not mapping:
            return data

        result = {}

        # Apply explicit mappings
        for spectra_field, tool_field in mapping.items():
            if tool_field in data:
                result[spectra_field] = data[tool_field]

        # Include unmapped fields
        mapped_tool_fields = set(mapping.values())
        for key, value in data.items():
            if key not in mapped_tool_fields:
                result[key] = value

        return result

