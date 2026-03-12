"""
Parser Agent — Intelligently parses security tool output using LLM.

Complements the regex-based ``output_intelligence.py`` by using LLM
for nuanced extraction that regex patterns miss.
"""

import logging
from typing import ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from app.services.ai.agents.registry import register_agent
from app.services.ai.context import ContextManager, ContextSection, Priority

logger = logging.getLogger("spectra.ai.agents.parser")


# --- Input/Output Models ---


class ParserInput(BaseModel):
    """Input for the ParserAgent."""

    tool_name: str = Field(..., description="Name of the tool that produced the output")
    tool_output: str = Field(..., description="Raw tool output text")
    target: str = Field("", description="Target that was scanned")


class ParsedFinding(BaseModel):
    """A single finding extracted from tool output."""

    type: str = Field(..., description="Finding type: vuln, port, service, credential, info")
    title: str = Field(..., description="Short title of the finding")
    description: str = Field("", description="Detailed description")
    severity: str = Field("info", description="Severity: critical, high, medium, low, info")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence score")
    evidence: str = Field("", description="Raw evidence from the output")


class ParserOutput(AgentAction):
    """Structured output from the ParserAgent."""

    action_type: str = "parsed_output"
    findings: list[ParsedFinding] = Field(default_factory=list)
    summary: str = Field("", description="Brief summary of the parsed output")
    next_actions: list[str] = Field(default_factory=list, description="Recommended follow-up actions")


# --- ParserAgent Implementation ---

PARSER_PROMPT = """Analyze the following security tool output and extract structured findings.

**Tool:** {tool_name}
**Target:** {target}

Extract ALL of the following if present:
- Vulnerabilities found (with CVE IDs if available)
- Open ports and services (with versions)
- Credentials discovered
- Attack surface elements (subdomains, endpoints, technologies)
- Recommended next actions based on findings

For each finding, assign:
- type: one of "vuln", "port", "service", "credential", "info"
- severity: one of "critical", "high", "medium", "low", "info"
- confidence: 0.0 to 1.0 based on how certain the finding is

Provide a brief summary and list of recommended next actions."""


@register_agent
class ParserAgent(Agent[ParserInput, ParserOutput]):
    """Intelligently parses security tool output using LLM."""

    role: ClassVar[AgentRole] = AgentRole.PARSER
    name: ClassVar[str] = "ParserAgent"
    description: ClassVar[str] = "Intelligently parses security tool output using LLM"

    async def execute(
        self,
        context: AgentContext,
        input_data: ParserInput,
    ) -> AgentResult:
        """Parse tool output into structured findings."""
        try:
            # Truncate very large outputs to fit context window
            max_output_len = 8000
            tool_output = input_data.tool_output[:max_output_len]
            if len(input_data.tool_output) > max_output_len:
                tool_output += "\n... [output truncated]"

            task_text = PARSER_PROMPT.format(
                tool_name=input_data.tool_name,
                target=input_data.target or context.target or "unknown",
            )

            ctx = ContextManager(max_context_tokens=6000)
            prompt = ctx.build(
                [
                    ContextSection("task", task_text, Priority.CRITICAL),
                    ContextSection(
                        "tool_output",
                        f"**Tool Output:**\n```\n{tool_output}\n```",
                        Priority.HIGH,
                        max_tokens=4000,
                    ),
                ]
            )

            action = await self._llm_generate_structured(
                prompt=prompt,
                response_model=ParserOutput,
                system_prompt=self._build_system_prompt(context),
                temperature=self._get_temperature(input_data),
            )

            return AgentResult(
                success=True,
                action=action,
                metadata={"findings_count": len(action.findings)},
            )

        except Exception as e:
            logger.error("ParserAgent failed: %s", e)
            return AgentResult(success=False, error=str(e))
