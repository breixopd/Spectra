"""
Vector Generator Agent.

Responsible for:
- Analyzing discovered services and web apps
- Generating potential attack vectors using AI
- Mapping services to tools and payloads dynamically
"""

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.models.attack_surface import AttackVector
from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)

logger = logging.getLogger("spectra.ai.agents.vector_generator")


class VectorGeneratorInput(BaseModel):
    """Input for the VectorGenerator."""

    target_type: str = Field(..., description="service, webapp, or vulnerability")
    target_data: dict[str, Any] = Field(..., description="Details of the target")
    context_notes: str | None = Field(None, description="Additional context")


class VectorGeneratorOutput(AgentAction):
    """Output from the VectorGenerator."""

    action_type: str = "generated_vectors"
    vectors: list[AttackVector] = Field(default_factory=list)


class VectorGeneratorAgent(Agent[VectorGeneratorInput, VectorGeneratorOutput]):
    """
    Agent that generates attack vectors dynamically.

    Instead of hardcoded rules, this agent uses the LLM to analyze
    the service/app and propose attack vectors based on its knowledge
    of security tools and vulnerabilities.
    """

    role: ClassVar[AgentRole] = AgentRole.MISSION_CONTROLLER  # Sub-role of controller
    name: ClassVar[str] = "VectorGenerator"
    description: ClassVar[str] = "Generates attack vectors for discovered assets"

    async def execute(
        self,
        context: AgentContext,
        input_data: VectorGeneratorInput,
    ) -> AgentResult:
        """Generate attack vectors."""
        try:
            action = await self._generate_with_llm(context, input_data)
            return AgentResult(success=True, action=action)
        except Exception as e:
            logger.error("VectorGenerator failed: %s", e)
            return AgentResult(success=False, error=str(e))

    async def _generate_with_llm(
        self,
        context: AgentContext,
        input_data: VectorGeneratorInput,
    ) -> VectorGeneratorOutput:
        """Use LLM to generate vectors with RAG augmentation."""
        from app.services.ai.knowledge import (
            get_available_tools_context,
            get_exploit_context,
        )

        # Build query from target data for RAG
        query_parts = []
        if input_data.target_data.get("service"):
            query_parts.append(input_data.target_data["service"])
        if input_data.target_data.get("product"):
            query_parts.append(input_data.target_data["product"])
        if input_data.target_data.get("version"):
            query_parts.append(input_data.target_data["version"])
        if input_data.target_data.get("technologies"):
            query_parts.extend(input_data.target_data["technologies"][:3])

        query = " ".join(query_parts) if query_parts else input_data.target_type

        # Get RAG context for similar past exploits using centralized service
        rag_context = await get_exploit_context(query)

        # Get available tools using centralized service
        tools_context = await get_available_tools_context(grouped=False)

        prompt = f"""Analyze this target and generate a list of attack vectors.

Target Type: {input_data.target_type}
Target Data: {input_data.target_data}
Context: {input_data.context_notes or "None"}

{rag_context}

{tools_context}

For each vector, specify:
1. A unique ID (e.g., "ssh-brute-192.168.1.1")
2. Name and description
3. Priority (critical, high, medium, low) - based on likelihood of success and impact
4. Suggested tools - **USE LOWERCASE TOOL IDs** (e.g., "metasploit", "nmap", "hydra", NOT "Metasploit Framework")
5. Specific payloads or parameters to try (MUST be a list of strings, NOT objects)
6. Max attempts (1-3)
7. Target Type (service, webapp, vulnerability)
8. Target Reference (e.g., "192.168.1.1:22", "http://example.com")

**IMPORTANT**: Use the exact lowercase tool IDs from the available tools list (e.g., "metasploit" not "Metasploit Framework").

Think like an experienced penetration tester following PTES methodology:
- What would you try first based on the service?
- What past successful exploits are relevant?
- What tools are available that can help?
- Consider default credentials, known CVEs, misconfigurations, and protocol-specific attacks.
"""

        system_prompt = self._build_system_prompt(context)

        try:
            response = await self.llm.generate_structured(
                prompt=prompt,
                response_model=VectorGeneratorOutput,
                system_prompt=system_prompt,
                temperature=0.4,
            )

            # Post-process to ensure IDs are unique, valid, and tool names are lowercase
            for vector in response.vectors:
                if not vector.target_type:
                    vector.target_type = input_data.target_type

                if not vector.target_ref:
                    if input_data.target_type == "service":
                        host = input_data.target_data.get("host", "unknown")
                        port = input_data.target_data.get("port", "0")
                        vector.target_ref = f"{host}:{port}"
                    elif input_data.target_type == "webapp":
                        vector.target_ref = input_data.target_data.get("url", "unknown")
                    else:
                        vector.target_ref = "unknown"

                # Normalize tool names to lowercase (tool IDs are lowercase)
                vector.suggested_tools = [
                    self._normalize_tool_name(t) for t in vector.suggested_tools
                ]

            return response

        except Exception as e:
            logger.error("LLM vector generation failed: %s", e)
            return VectorGeneratorOutput(
                confidence=0.0,
                risk_level=ActionRisk.LOW,
                reasoning="Failed to generate vectors: %s" % e,
                vectors=[],
            )

    def _normalize_tool_name(self, tool_name: str) -> str:
        """
        Normalize tool names to match plugin IDs.

        LLMs often use title-case like "Metasploit Framework" or "Hydra"
        but plugin IDs are lowercase like "metasploit" or "hydra".
        """
        # Map of common LLM variations to plugin IDs
        tool_aliases = {
            "metasploit framework": "metasploit",
            "metasploit": "metasploit",
            "hydra": "hydra",
            "nuclei": "nuclei",
            "nmap": "nmap",
            "nikto": "nikto",
            "gobuster": "gobuster",
            "wpscan": "wpscan",
            "sqlmap": "sqlmap",
            "searchsploit": "searchsploit",
            "ffuf": "ffuf",
            "naabu": "naabu",
            "amass": "amass",
        }

        normalized = tool_name.lower().strip()
        return tool_aliases.get(normalized, normalized)
