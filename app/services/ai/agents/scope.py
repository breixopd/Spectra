"""
ScopeAgent - Parses user input to define mission scope.

Responsible for:
- Validating and parsing target specifications (IPs, domains, CIDRs)
- Defining assessment boundaries
- Identifying exclusions and restrictions
"""

import ipaddress
import logging
import re
from typing import ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from app.services.ai.prompts import SCOPE_PARSING_PROMPT

logger = logging.getLogger("spectra.ai.agents.scope")


# --- Input/Output Models ---


class ScopeInput(BaseModel):
    """Input for the ScopeAgent."""

    raw_input: str = Field(..., description="Raw user input to parse")
    include_subdomains: bool = Field(True, description="Include subdomains in scope")
    max_hosts: int = Field(256, description="Maximum hosts to include")


class TargetSpec(BaseModel):
    """Specification for a single target."""

    value: str = Field(..., description="Target value (IP, domain, CIDR)")
    target_type: str = Field(..., description="Type: ip, domain, cidr, url")
    resolved_ips: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    notes: str = Field("", description="Additional notes")


class ScopeAction(AgentAction):
    """Output from the ScopeAgent."""

    action_type: str = "define_scope"
    targets: list[TargetSpec] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    total_hosts: int = Field(0, description="Estimated total hosts in scope")
    warnings: list[str] = Field(default_factory=list)


# --- ScopeAgent Implementation ---


class ScopeAgent(Agent[ScopeInput, ScopeAction]):
    """
    Agent that parses user input to define the mission scope.

    Combines regex-based parsing for common patterns with
    LLM-based understanding for complex or ambiguous inputs.
    """

    role: ClassVar[AgentRole] = AgentRole.SCOPE
    name: ClassVar[str] = "ScopeAgent"
    description: ClassVar[str] = "Parses user input to define strict assessment boundaries (IPs, domains, CIDRs)"

    # Regex patterns for common target types
    IP_PATTERN = re.compile(
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
    )
    CIDR_PATTERN = re.compile(
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)/(?:[0-9]|[12][0-9]|3[0-2])\b"
    )
    DOMAIN_PATTERN = re.compile(
        r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+" r"[a-zA-Z]{2,}\b"
    )
    URL_PATTERN = re.compile(r"https?://[^\s]+")
    PORT_RANGE_PATTERN = re.compile(r":(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)")

    async def execute(
        self,
        context: AgentContext,
        input_data: ScopeInput,
    ) -> AgentResult:
        """Parse input and define scope."""
        try:
            # First try regex-based extraction
            targets, warnings = self._extract_targets(input_data.raw_input)

            # If no targets found or input seems complex, use LLM
            if not targets or self._is_complex_input(input_data.raw_input):
                llm_result = await self._parse_with_llm(context, input_data)
                if llm_result.targets:
                    # Merge with regex results
                    existing_values = {t.value for t in targets}
                    for t in llm_result.targets:
                        if t.value not in existing_values:
                            targets.append(t)
                    warnings.extend(llm_result.warnings)

            # Validate and calculate total hosts
            validated_targets = []
            total_hosts = 0

            for target in targets:
                is_valid, host_count = self._validate_target(target)
                if is_valid:
                    validated_targets.append(target)
                    total_hosts += host_count
                else:
                    warnings.append(f"Invalid target skipped: {target.value}")

            # Check against max_hosts limit
            if total_hosts > input_data.max_hosts:
                warnings.append(
                    f"Scope exceeds max hosts ({total_hosts} > {input_data.max_hosts}). "
                    "Consider narrowing the scope."
                )

            action = ScopeAction(
                confidence=0.9 if validated_targets else 0.3,
                risk_level=ActionRisk.LOW,
                reasoning=f"Parsed {len(validated_targets)} targets from input",
                targets=validated_targets,
                total_hosts=min(total_hosts, input_data.max_hosts),
                warnings=warnings,
            )

            return AgentResult(
                success=bool(validated_targets),
                action=action,
                error=None if validated_targets else "No valid targets found",
            )

        except Exception as e:
            logger.error("ScopeAgent failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )

    def _extract_targets(self, text: str) -> tuple[list[TargetSpec], list[str]]:
        """Extract targets using regex patterns."""
        targets = []
        warnings = []
        seen = set()

        # Extract CIDRs first (before IPs to avoid partial matches)
        for match in self.CIDR_PATTERN.finditer(text):
            value = match.group()
            if value not in seen:
                seen.add(value)
                targets.append(
                    TargetSpec(
                        value=value,
                        target_type="cidr",
                        notes="",
                    )
                )

        # Extract URLs
        for match in self.URL_PATTERN.finditer(text):
            value = match.group()
            if value not in seen:
                seen.add(value)
                targets.append(
                    TargetSpec(
                        value=value,
                        target_type="url",
                        notes="",
                    )
                )

        # Extract standalone IPs (not already in CIDRs)
        for match in self.IP_PATTERN.finditer(text):
            value = match.group()
            # Check not part of a CIDR
            if value not in seen and not any(value in s for s in seen):
                seen.add(value)
                targets.append(
                    TargetSpec(
                        value=value,
                        target_type="ip",
                        notes="",
                    )
                )

        # Extract domains (not from URLs)
        for match in self.DOMAIN_PATTERN.finditer(text):
            value = match.group().lower()
            # Skip if likely part of a URL already captured
            if value not in seen and not any(value in s for s in seen):
                seen.add(value)
                targets.append(
                    TargetSpec(
                        value=value,
                        target_type="domain",
                        notes="",
                    )
                )

        return targets, warnings

    def _is_complex_input(self, text: str) -> bool:
        """Check if input requires LLM interpretation."""
        complex_indicators = [
            "except",
            "exclude",
            "but not",
            "only",
            "internal",
            "external",
            "production",
            "staging",
            "range",
            "between",
            "all",
            "any",
        ]
        text_lower = text.lower()
        return any(ind in text_lower for ind in complex_indicators)

    async def _parse_with_llm(
        self,
        context: AgentContext,
        input_data: ScopeInput,
    ) -> ScopeAction:
        """Use LLM to parse complex input."""
        prompt = SCOPE_PARSING_PROMPT.format(raw_input=input_data.raw_input)

        system_prompt = self._build_system_prompt(context)

        try:
            return await self.llm.generate_structured(
                prompt=prompt,
                response_model=ScopeAction,
                system_prompt=system_prompt,
                temperature=0.2,  # Low temperature for parsing
            )
        except Exception as e:
            logger.warning("LLM parsing failed, using regex only: %s", e)
            return ScopeAction(
                confidence=0.5,
                risk_level=ActionRisk.LOW,
                reasoning="LLM parsing failed, using regex extraction only",
                targets=[],
                total_hosts=0,
                warnings=[str(e)],
            )

    def _validate_target(self, target: TargetSpec) -> tuple[bool, int]:
        """Validate a target and return (is_valid, host_count)."""
        try:
            if target.target_type == "ip":
                ipaddress.ip_address(target.value)
                return True, 1

            elif target.target_type == "cidr":
                network = ipaddress.ip_network(target.value, strict=False)
                return True, network.num_addresses

            elif target.target_type == "domain":
                # Basic domain validation
                if len(target.value) > 253:
                    return False, 0
                if not all(
                    len(label) <= 63 and label for label in target.value.split(".")
                ):
                    return False, 0
                return True, 1  # Count as 1, may resolve to multiple IPs

            elif target.target_type == "url":
                # URL is valid if it has a scheme and host
                return "://" in target.value, 1

            return False, 0

        except ValueError:
            return False, 0
