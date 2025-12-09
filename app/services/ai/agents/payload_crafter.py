"""
PayloadCrafter Agent - Generates and selects exploits.

Responsible for:
- Analyzing vulnerability scan results
- Searching for matching exploits (via SearchSploit)
- Crafting payloads for specific targets
- Validating payload safety
"""

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentContext,
    AgentResult,
    AgentRole,
    ToolAction,
)
from app.services.ai.prompts import EXPLOIT_SELECTION_PROMPT

logger = logging.getLogger("spectra.ai.agents.payload_crafter")


class PayloadCrafterInput(BaseModel):
    """Input for the PayloadCrafter."""

    vulnerability: dict[str, Any] = Field(..., description="The vulnerability to exploit")
    target: str = Field(..., description="Target IP/Domain")
    target_os: str | None = Field(None, description="Target OS if known")
    protocol: str | None = Field(None, description="Target protocol (http, ssh, etc)")


class PayloadCrafterOutput(ToolAction):
    """Output from the PayloadCrafter."""

    exploit_name: str = Field(..., description="Name/ID of the exploit to use")
    payload_type: str = Field(..., description="Type of payload (reverse_shell, bind_shell, etc)")


class PayloadCrafterAgent(Agent[PayloadCrafterInput, PayloadCrafterOutput]):
    """
    Agent that crafts exploits and payloads.

    It bridges the gap between finding a vulnerability (Nuclei/Nmap)
    and exploiting it (Metasploit/Scripts).
    """

    role: ClassVar[AgentRole] = (
        AgentRole.EXPLOIT_CRAFTER
    )  # Using EXPLOIT_CRAFTER as this agent crafts payloads/exploits
    name: ClassVar[str] = "PayloadCrafter"
    description: ClassVar[str] = "Selects and customizes exploits for identified vulnerabilities"

    async def execute(
        self,
        context: AgentContext,
        input_data: PayloadCrafterInput,
    ) -> AgentResult:
        """Select and craft an exploit."""
        try:
            # Use LLM to analyze the vuln and suggest an exploit
            action = await self._craft_with_llm(context, input_data)

            # High risk by default for exploitation
            action.risk_level = ActionRisk.HIGH

            return AgentResult(
                success=True,
                action=action,
            )

        except Exception as e:
            logger.error("PayloadCrafter failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )

    async def _craft_with_llm(
        self,
        context: AgentContext,
        input_data: PayloadCrafterInput,
    ) -> PayloadCrafterOutput:
        """Use LLM to select exploit."""
        previous_failures = []
        if context.previous_actions:
            for a in context.previous_actions:
                if "error" in a or "result" in a:
                    previous_failures.append(f"- {a.get('error') or a.get('result')}")
        
        prompt = EXPLOIT_SELECTION_PROMPT.format(
            target=input_data.target,
            vulnerability_name=input_data.vulnerability.get("name", "Unknown"),
            vulnerability_desc=input_data.vulnerability.get("description", "N/A"),
            vulnerability_details=input_data.vulnerability,
            previous_failures="\n".join(previous_failures) if previous_failures else "None",
        )

        system_prompt = self._build_system_prompt(context)

        return await self.llm.generate_structured(
            prompt=prompt,
            response_model=PayloadCrafterOutput,
            system_prompt=system_prompt,
            temperature=0.4,  # Slightly creative but grounded
        )
