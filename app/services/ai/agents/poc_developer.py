"""
POC Developer Agent.

Specialized agent for writing custom exploit scripts.
"""
import logging
from typing import ClassVar, Any

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    Agent,
    AgentContext,
    AgentResult,
    AgentRole,
    ToolAction,
    ActionRisk,
)
from app.services.poc.models import POCRequest

logger = logging.getLogger("spectra.ai.agents.poc_developer")

POC_DEVELOPER_PROMPT = """You are an expert Exploit Developer specializing in creating Proof-of-Concept (POC) scripts for security assessments.

YOUR GOAL: Write a working, self-contained exploit script for the specified vulnerability.

INPUT CONTEXT:
Target: {target}
Vulnerability: {vulnerability_name}
Description: {vulnerability_desc}
Port: {port}
Protocol: {protocol}

REQUIREMENTS:
1. Language: Prefer Python 3. If not feasible, use Bash or Go.
2. Stability: The script must be robust and handle connection errors gracefully.
3. Payload: Implement a {shell_type} payload.
   - If Reverse Shell: Connect back to {callback_host}:{callback_port}.
   - If Bind Shell: Bind to a random port and print it.
   - If Command Exec: Execute 'whoami' or 'id' to verify.
4. Output: The script should print "[+] Exploit Successful" if it works.

CONSTRAINTS:
- Do NOT use external dependencies that are not standard (e.g., use 'socket', 'requests', 'sys').
- Code must be clean, commented, and safe (no destructive actions).
- Return ONLY the code block, or structured JSON if requested.

Generative Task:
Write the complete source code for this exploit.
"""

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

class POCDeveloperAgent(Agent[POCDeveloperInput, POCDeveloperOutput]):
    """
    Agent that writes custom exploit code.
    """

    role: ClassVar[AgentRole] = AgentRole.EXPLOIT_CRAFTER
    name: ClassVar[str] = "POCDeveloper"
    description: ClassVar[str] = "Writes custom exploit scripts (Python/Go/Bash) for specific vulnerabilities."

    async def execute(
        self,
        context: AgentContext,
        input_data: POCDeveloperInput,
    ) -> AgentResult:
        try:
            vuln = input_data.request.vulnerability

            prompt = POC_DEVELOPER_PROMPT.format(
                target=input_data.request.target,
                vulnerability_name=vuln.get("name", "Unknown"),
                vulnerability_desc=vuln.get("description", "N/A"),
                port=input_data.request.port or "Unknown",
                protocol=input_data.request.protocol,
                shell_type=input_data.shell_type,
                callback_host=input_data.callback_host,
                callback_port=input_data.callback_port,
            )

            system_prompt = (
                "You are a senior security researcher writing educational exploit code. "
                "Ensure code follows safe coding practices and PTES methodology. "
                "Focus on reliability and stealth."
            )

            action = await self.llm.generate_structured(
                prompt=prompt,
                response_model=POCDeveloperOutput,
                system_prompt=system_prompt,
                temperature=0.2, # Low temp for code correctness
            )

            # Set high risk for custom code execution
            action.risk_level = ActionRisk.HIGH

            return AgentResult(success=True, action=action)

        except Exception as e:
            logger.error(f"POC Developer failed: {e}")
            return AgentResult(success=False, error=str(e))
