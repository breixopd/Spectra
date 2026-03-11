"""
Safety Supervisor Agent.

Responsible for:
- Intercepting tool commands before execution.
- Analyzing commands for dangerous patterns (rm -rf, etc.).
- Using LLM to evaluate context-aware safety (e.g., "Is this DROP TABLE safe in this context?").
- Enforcing the "Red-Flagging" mechanism of the MAKER framework.
"""

import logging
import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from app.services.ai.agents.registry import register_agent
from app.services.ai.context import ContextManager, ContextSection, Priority

logger = logging.getLogger("spectra.ai.agents.safety")


class SafetyInput(BaseModel):
    """Input for the Safety Supervisor."""

    command: str
    tool_id: str
    target: str
    args: dict[str, Any] = Field(default_factory=dict)


class SafetyAction(AgentAction):
    """Decision on whether to allow the command."""

    action_type: str = "safety_check"
    allowed: bool
    modification: str | None = None  # If modified command is suggested
    reason: str


@register_agent
class SafetySupervisorAgent(Agent[SafetyInput, SafetyAction]):
    """
    Agent that guards against dangerous operations.

    It uses a hybrid approach:
    1. Regex Blocklist: Instant blocking of known bad patterns.
    2. LLM Analysis: Contextual understanding of complex commands.
    """

    role: ClassVar[AgentRole] = AgentRole.SAFETY_SUPERVISOR
    name: ClassVar[str] = "SafetySupervisor"
    description: ClassVar[str] = "Evaluates commands for safety and security risks"

    # Regex patterns for immediate blocking (Red Flags)
    BLOCKLIST = [
        r"rm\s+-rf\s+/$",  # rm -rf /
        r"rm\s+-rf\s+/\*",  # rm -rf /*
        r"mkfs\.",  # Formatting
        r":\(\)\{\s*:\|:\s*&\s*\};:",  # Fork bomb
        r">\s*/etc/passwd",  # Overwriting system files
        r">\s*/etc/shadow",
        r"dd\s+if=.*of=/dev/",  # Direct disk writing
    ]

    # Large wordlist patterns to block (anti-brute-force policy)
    BRUTEFORCE_BLOCKLIST = [
        r"rockyou",  # rockyou.txt
        r"SecLists.*Password",  # SecLists password lists
        r"darkweb.*top",  # Darkweb password dumps
        r"/usr/share/wordlists/.*password",  # System wordlists
        r"-P\s+/.*\.txt",  # Hydra with file-based password list
        r"-L\s+/.*\.txt",  # Hydra with file-based user list
        r"--passwords?\s+/.*\.txt",  # Generic password file args
        r"-w\s+/usr/share/seclists.*(Password|Credential)",  # Wordlist dirs
    ]

    @classmethod
    def check_blocklist(cls, command: str) -> tuple[bool, str]:
        """Check a command against regex blocklists without LLM.

        Returns:
            (allowed, reason) — allowed is False if blocked.
        """
        for pattern in cls.BLOCKLIST:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Matches known dangerous command pattern: {pattern}"
        for pattern in cls.BRUTEFORCE_BLOCKLIST:
            if re.search(pattern, command, re.IGNORECASE):
                return False, "Large wordlist brute-force is not allowed"
        return True, "OK"

    async def execute(
        self,
        context: AgentContext,
        input_data: SafetyInput,
    ) -> AgentResult:
        """Evaluate the safety of a command."""
        logger.info("Safety check: tool=%s target=%s", input_data.tool_id, input_data.target)

        # 1. Fast Path: Regex Blocklist
        for pattern in self.BLOCKLIST:
            if re.search(pattern, input_data.command, re.IGNORECASE):
                logger.warning("Blocked command by regex pattern: %s (tool=%s)", pattern, input_data.tool_id)
                return AgentResult(
                    success=True,
                    action=SafetyAction(
                        confidence=1.0,
                        risk_level=ActionRisk.CRITICAL,
                        reasoning=f"Blocked by regex pattern: {pattern}",
                        allowed=False,
                        reason="Matches known dangerous command pattern",
                    ),
                )

        # 1b. Brute-force policy: block large wordlists
        for pattern in self.BRUTEFORCE_BLOCKLIST:
            if re.search(pattern, input_data.command, re.IGNORECASE):
                return AgentResult(
                    success=True,
                    action=SafetyAction(
                        confidence=1.0,
                        risk_level=ActionRisk.HIGH,
                        reasoning=f"Blocked large wordlist brute-force: {pattern}",
                        allowed=False,
                        reason="Large wordlist brute-force is not allowed. "
                        "Only default/common credentials are permitted.",
                    ),
                )

        # 2. Slow Path: LLM Analysis
        # We use a low temperature for strictness
        base_prompt = """Analyze this command for safety.

Is this command safe to execute in a controlled security assessment?
CONTEXT: The command runs inside a SANDBOXED DOCKER CONTAINER ('spectra-tools').
- Standard scanning/exploitation tooks (nmap, curl, etc.) are EXPECTED.
- File system operations (rm, cp, mv) are SAFE if they affect the container's temporary files.
- Dangerous operations are those that escape the container or destroy persistence volumes.

Standard reconnaissance and scanning tools (nmap, nikto, sqlmap, etc.) are ALLOWED if they target the authorized host.
Exploitation tools are ALLOWED if they target the authorized host and are part of the mission.

Dangerous actions that should be BLOCKED (High Risk):
1. Targeting hosts NOT in the scope
2. Denial of Service (DoS) attacks (unless authorized)
3. Data exfiltration to unauthorized external IPs

BLOCK if:
- Command targets out-of-scope IP.
- Command tries to wipe mounted volumes (data/plugins).
- Command is a clear fork bomb or resource exhaustion.

Provide a JSON response with:
- allowed: boolean
- reason: string (short explanation)
- reasoning: string (detailed analysis)
- confidence: float (0.0 to 1.0)
- risk_level: "low", "medium", "high", or "critical"
"""

        from app.services.ai.sanitizer import sanitize_for_prompt
        sanitized_target = sanitize_for_prompt(input_data.target, field_name="safety_target")
        command_info = f"Command: `{input_data.command}`\nTool: {input_data.tool_id}\nTarget: {sanitized_target}"

        ctx = ContextManager(max_context_tokens=2000)
        prompt = ctx.build([
            ContextSection("task", base_prompt, Priority.CRITICAL),
            ContextSection("command", command_info, Priority.HIGH, max_tokens=500),
            ContextSection("mission", f"Mission context: {context.mission}", Priority.MEDIUM, max_tokens=200),
        ])

        try:
            action = await self._llm_generate_structured(
                prompt=prompt,
                response_model=SafetyAction,
                system_prompt=self._build_system_prompt(context),
                temperature=0.1,  # Low temp for safety
            )

            return AgentResult(success=True, action=action)

        except Exception as e:
            logger.error("Safety check failed: %s", e)
            # Fail safe: Block if we can't decide
            return AgentResult(
                success=False,
                error=str(e),
                action=SafetyAction(
                    confidence=0.0,
                    risk_level=ActionRisk.HIGH,
                    reasoning="Safety check failed, blocking by default",
                    allowed=False,
                    reason="Internal error during safety check",
                ),
            )
