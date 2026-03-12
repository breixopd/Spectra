"""
POC Developer Agent.

Specialized agent for writing custom exploit scripts.
"""

import logging
from typing import ClassVar

from pydantic import BaseModel

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentContext,
    AgentResult,
    AgentRole,
    ToolAction,
)
from app.services.ai.agents.registry import register_agent
from app.services.ai.context import ContextManager, ContextSection, Priority
from app.services.ai.prompts import POC_DEVELOPER_PROMPT
from app.services.poc.models import POCRequest

logger = logging.getLogger("spectra.ai.agents.poc_developer")


class POCDeveloperInput(BaseModel):
    request: POCRequest
    callback_host: str
    callback_port: int
    shell_type: str = "reverse_shell"


class POCDeveloperOutput(ToolAction):
    """Output containing the generated code."""

    language: str
    code_content: str
    usage_instructions: str
    risk_assessment: str


@register_agent
class POCDeveloperAgent(Agent[POCDeveloperInput, POCDeveloperOutput]):
    """
    Agent that writes custom exploit code.
    """

    role: ClassVar[AgentRole] = AgentRole.POC_DEVELOPER
    name: ClassVar[str] = "POCDeveloper"
    description: ClassVar[str] = "Writes custom exploit scripts (Python/Go/Bash) for specific vulnerabilities."
    enable_reflection: ClassVar[bool] = True
    reflection_threshold: ClassVar[float] = 0.75

    async def execute(
        self,
        context: AgentContext,
        input_data: POCDeveloperInput,
    ) -> AgentResult:
        try:
            vuln = input_data.request.vulnerability

            full_prompt = POC_DEVELOPER_PROMPT.format(
                target=input_data.request.target,
                vulnerability_name=vuln.get("name", "Unknown"),
                vulnerability_desc=vuln.get("description", "N/A"),
                port=input_data.request.port or "Unknown",
                protocol=input_data.request.protocol,
                shell_type=input_data.shell_type,
                callback_host=input_data.callback_host,
                callback_port=input_data.callback_port,
            )

            vuln_desc = vuln.get("description", "N/A")
            target_details = (
                f"Target: {input_data.request.target}\n"
                f"Port: {input_data.request.port or 'Unknown'}\n"
                f"Protocol: {input_data.request.protocol}"
            )

            ctx = ContextManager(max_context_tokens=3000)
            prompt = ctx.build(
                [
                    ContextSection("task", full_prompt, Priority.CRITICAL),
                    ContextSection(
                        "vulnerability", f"Vulnerability Description:\n{vuln_desc}", Priority.HIGH, max_tokens=500
                    ),
                    ContextSection("target", f"Target Details:\n{target_details}", Priority.MEDIUM, max_tokens=300),
                ]
            )

            system_prompt = (
                "You are a senior security researcher writing educational exploit code. "
                "Ensure code follows safe coding practices and PTES methodology. "
                "Focus on reliability and stealth."
            )

            action = await self._llm_generate_structured(
                prompt=prompt,
                response_model=POCDeveloperOutput,
                system_prompt=system_prompt,
                temperature=0.2,  # Low temp for code correctness
            )

            # Set high risk for custom code execution
            action.risk_level = ActionRisk.HIGH

            return AgentResult(success=True, action=action)

        except Exception as e:
            logger.error("POC Developer failed: %s", e)
            return AgentResult(success=False, error=str(e))
