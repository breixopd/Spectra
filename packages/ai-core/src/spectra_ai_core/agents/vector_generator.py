"""
Vector Generator Agent.

Responsible for:
- Analyzing discovered services and web apps
- Generating potential attack vectors using AI
- Mapping services to tools and payloads dynamically
"""

import logging
import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from spectra_ai_core.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from spectra_ai_core.agents.registry import register_agent
from spectra_ai_core.context import ContextManager, ContextSection, Priority
from spectra_ai_core.sanitizer import sanitize_for_prompt
from spectra_persistence.models.attack_surface import AttackVector, VectorPriority

logger = logging.getLogger(__name__)


class VectorGeneratorInput(BaseModel):
    """Input for the VectorGenerator."""

    target_type: str = Field(..., description="service, webapp, or vulnerability")
    target_data: dict[str, Any] = Field(..., description="Details of the target")
    context_notes: str | None = Field(None, description="Additional context")


class VectorGeneratorOutput(AgentAction):
    """Output from the VectorGenerator."""

    action_type: str = "generated_vectors"
    vectors: list[AttackVector] = Field(default_factory=list)


@register_agent
class VectorGeneratorAgent(Agent[VectorGeneratorInput, VectorGeneratorOutput]):
    """
    Agent that generates attack vectors dynamically.

    Instead of hardcoded rules, this agent uses the LLM to analyze
    the service/app and propose attack vectors based on its knowledge
    of security tools and vulnerabilities.
    """

    role: ClassVar[AgentRole] = AgentRole.VECTOR_GENERATOR
    name: ClassVar[str] = "VectorGenerator"
    description: ClassVar[str] = "Generates attack vectors for discovered assets"
    enable_reflection: ClassVar[bool] = True
    reflection_threshold: ClassVar[float] = 0.65

    # Deterministic vector templates keyed by service keyword
    DETERMINISTIC_VECTORS: ClassVar[dict[str, list[dict[str, Any]]]] = {
        "http": [
            {"name": "Directory Brute Force", "tools": ["dirsearch", "gobuster", "ffuf"], "phase": "recon"},
            {"name": "Web Vulnerability Scan", "tools": ["nuclei", "nikto"], "phase": "vuln_scan"},
            {"name": "SQL Injection", "tools": ["sqlmap"], "phase": "exploitation"},
            {"name": "CMS Detection + Exploitation", "tools": ["whatweb", "wpscan"], "phase": "recon"},
        ],
        "smb": [
            {"name": "SMB Enumeration", "tools": ["enum4linux", "crackmapexec"], "phase": "recon"},
            {
                "name": "EternalBlue Check",
                "tools": ["nmap"],
                "nmap_scripts": ["smb-vuln-ms17-010"],
                "phase": "vuln_scan",
            },
            {"name": "SMB Brute Force", "tools": ["hydra", "crackmapexec"], "phase": "exploitation"},
        ],
        "ssh": [
            {"name": "SSH Version Check", "tools": ["nmap"], "phase": "recon"},
            {"name": "SSH Brute Force", "tools": ["hydra"], "phase": "exploitation"},
        ],
        "ftp": [
            {"name": "Anonymous FTP Check", "tools": ["nmap"], "nmap_scripts": ["ftp-anon"], "phase": "recon"},
            {"name": "FTP Version Exploit", "tools": ["searchsploit", "metasploit"], "phase": "exploitation"},
        ],
        "mysql": [
            {"name": "MySQL Brute Force", "tools": ["hydra"], "phase": "exploitation"},
            {
                "name": "MySQL Enumeration",
                "tools": ["nmap"],
                "nmap_scripts": ["mysql-info", "mysql-databases"],
                "phase": "recon",
            },
        ],
        "dns": [
            {"name": "DNS Zone Transfer", "tools": ["nmap"], "nmap_scripts": ["dns-zone-transfer"], "phase": "recon"},
            {"name": "Subdomain Enumeration", "tools": ["subfinder", "amass"], "phase": "recon"},
        ],
    }

    @classmethod
    def generate_deterministic_vectors(cls, services: dict[int, str]) -> list[dict[str, Any]]:
        """Generate attack vectors based on detected services without LLM."""
        vectors: list[dict[str, Any]] = []
        for port, service in services.items():
            service_lower = service.lower()
            for key, vecs in cls.DETERMINISTIC_VECTORS.items():
                if key in service_lower:
                    for vec in vecs:
                        vectors.append({**vec, "target_port": port, "target_service": service})
        return vectors

    async def execute(
        self,
        context: AgentContext,
        input_data: VectorGeneratorInput,
    ) -> AgentResult:
        """Generate attack vectors: deterministic first, then LLM for creative vectors."""
        try:
            # 1. Deterministic vectors from service data
            det_vectors: list[AttackVector] = []
            target_data = input_data.target_data
            if target_data.get("port") and target_data.get("service"):
                services = {int(target_data["port"]): str(target_data["service"])}
                raw = self.generate_deterministic_vectors(services)
                phase_priorities = {
                    "recon": VectorPriority.MEDIUM,
                    "vuln_scan": VectorPriority.HIGH,
                    "exploitation": VectorPriority.HIGH,
                }
                for rv in raw:
                    host = target_data.get("host", "unknown")
                    port = rv.get("target_port", target_data.get("port", 0))
                    det_vectors.append(
                        AttackVector(
                            id=f"det-{uuid.uuid4().hex[:8]}",
                            name=rv["name"],
                            description=f"Deterministic vector for {rv.get('target_service', '')}",
                            priority=phase_priorities.get(rv.get("phase", ""), VectorPriority.MEDIUM),
                            suggested_tools=rv["tools"],
                            target_type=input_data.target_type,
                            target_ref=f"{host}:{port}",
                        )
                    )

            # 2. LLM-generated creative vectors
            action = await self._generate_with_llm(context, input_data)

            # Merge: deterministic first, then LLM
            if det_vectors:
                action.vectors = det_vectors + action.vectors

            return AgentResult(success=True, action=action)
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.error("VectorGenerator failed: %s", e)
            return AgentResult(success=False, error=str(e))

    async def _generate_with_llm(
        self,
        context: AgentContext,
        input_data: VectorGeneratorInput,
    ) -> VectorGeneratorOutput:
        """Use LLM to generate vectors with RAG augmentation."""
        from spectra_ai_core.knowledge import (
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
        rag_context = await get_exploit_context(
            query,
            user_id=context.user_id,
            exclude_session_id=context.mission_id,
        )

        # Get available tools using centralized service
        tools_context = await get_available_tools_context(grouped=False)

        base_prompt = f"""Analyze this target and generate a list of attack vectors.

Target Type: {input_data.target_type}

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
- Consider default credentials, known CVEs, misconfigurations, and protocol-specific attacks."""

        ctx = ContextManager(max_context_tokens=6000)
        prompt = ctx.build(
            [
                ContextSection("task", base_prompt, Priority.CRITICAL),
                ContextSection(
                    "target_data",
                    f"Target Data: {sanitize_for_prompt(str(input_data.target_data), field_name='target_data')}",
                    Priority.HIGH,
                    max_tokens=500,
                ),
                ContextSection("tools", tools_context, Priority.HIGH, max_tokens=800),
                ContextSection("rag", rag_context, Priority.MEDIUM, max_tokens=500),
                ContextSection(
                    "context_notes",
                    f"Context: {sanitize_for_prompt(input_data.context_notes or 'None', field_name='context_notes')}",
                    Priority.LOW,
                    max_tokens=200,
                ),
            ]
        )

        system_prompt = self._build_system_prompt(context)

        try:
            response = await self._llm_generate_structured(
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
                vector.suggested_tools = [self._normalize_tool_name(t) for t in vector.suggested_tools]

            return response

        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.error("LLM vector generation failed: %s", e)
            return VectorGeneratorOutput(
                confidence=0.0,
                risk_level=ActionRisk.LOW,
                reasoning=f"Failed to generate vectors: {e}",
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
