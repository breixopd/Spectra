"""
Parameter Tuner Agent — Tunes security tool parameters based on target context.

Uses domain knowledge about common security tools to optimize parameters
for the specific target, phase, and stealth requirements.
"""

import logging
from typing import Any, ClassVar

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

logger = logging.getLogger("spectra.ai.agents.parameter_tuner")


# --- Input/Output Models ---


class TunerInput(BaseModel):
    """Input for the ParameterTunerAgent."""

    tool_name: str = Field(..., description="Name of the tool to tune")
    target: str = Field(..., description="Target to scan")
    target_type: str = Field("ip", description="Type: ip, domain, network")
    phase: str = Field("discovery", description="Current assessment phase")
    stealth_mode: bool = Field(False, description="Whether to minimize detection")
    previous_results: list[dict[str, Any]] = Field(
        default_factory=list, description="Results from previously run tools"
    )


class TunerOutput(AgentAction):
    """Tuned parameters for a security tool."""

    action_type: str = "tune_parameters"
    tool_args: dict[str, Any] = Field(default_factory=dict, description="Optimized tool arguments")
    timeout: int = Field(300, description="Recommended timeout in seconds")
    environment: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    notes: str = Field("", description="Explanation of tuning decisions")


# --- Domain knowledge for tool parameter tuning ---

TOOL_KNOWLEDGE: dict[str, str] = {
    "nmap": (
        "Nmap parameters: -sV (version detection), -sC (default scripts), "
        "-O (OS detection), -T0-T5 (timing: paranoid to insane), "
        "-p- (all ports), --top-ports N, -sS (SYN scan), -sT (TCP connect), "
        "-sU (UDP scan), --script <category> (vuln, auth, brute, discovery, exploit), "
        "-Pn (skip host discovery), --min-rate/--max-rate, "
        "-oX/-oN/-oG (output formats). "
        "For stealth: use -T1 or -T2, --scan-delay 1s, -sS. "
        "For thoroughness: -sV -sC -O -p- --script vuln."
    ),
    "nuclei": (
        "Nuclei parameters: -severity critical,high,medium,low, "
        "-tags cve,misconfig,exposure, -rate-limit N, -bulk-size N, "
        "-concurrency N, -retries N, -timeout N, "
        "-type http,dns,network, -exclude-tags dos. "
        "For stealth: -rate-limit 5 -bulk-size 5. "
        "For thoroughness: -severity critical,high,medium."
    ),
    "gobuster": (
        "Gobuster parameters: dir mode: -w (wordlist), -x (extensions like php,asp,html), "
        "-t (threads, default 10), -s (status codes), --no-error, "
        "-b (blacklist status codes), -r (follow redirects). "
        "Common wordlists: /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt, "
        "/usr/share/seclists/Discovery/Web-Content/common.txt. "
        "For stealth: -t 2 --delay 500ms."
    ),
    "ffuf": (
        "FFUF parameters: -w (wordlist), -u (URL with FUZZ keyword), "
        "-mc (match codes), -fc (filter codes like 404), -t (threads), "
        "-rate (requests/sec), -timeout N, -e (extensions), "
        "-recursion -recursion-depth N. "
        "For stealth: -rate 5 -t 2."
    ),
    "sqlmap": (
        "SQLMap parameters: --level 1-5 (test thoroughness), "
        "--risk 1-3 (risk of tests), --technique BEUSTQ, "
        "--dbms (target DBMS), --os (target OS), "
        "--threads N, --batch (non-interactive), --random-agent, "
        "--tamper (evasion scripts). "
        "For stealth: --random-agent --tamper=space2comment --delay 2."
    ),
    "hydra": (
        "Hydra parameters: -l/-L (login/login list), -p/-P (password/password list), "
        "-t (parallel tasks), -f (stop on first success), -v (verbose), "
        "-s (port), protocol://target. "
        "Supported protocols: ssh, ftp, http-get, http-post-form, mysql, smb, rdp."
    ),
    "naabu": (
        "Naabu parameters: -p (ports or -p -), -rate N, "
        "-c (concurrency), -timeout N, -retries N, "
        "-top-ports N, -exclude-ports. "
        "For stealth: -rate 50 -c 5."
    ),
}

# Tools with complex parameter spaces that benefit from tuning
COMPLEX_TOOLS = frozenset(
    {
        "nmap",
        "nuclei",
        "gobuster",
        "ffuf",
        "sqlmap",
        "hydra",
        "naabu",
        "dirsearch",
        "wpscan",
        "metasploit",
        "crackmapexec",
        "feroxbuster",
        "nikto",
        "amass",
        "subfinder",
    }
)

TUNER_PROMPT = """You are a security tool parameter tuner. Given the context below,
generate optimal parameters for the tool.

**Tool:** {tool_name}
**Target:** {target} (type: {target_type})
**Phase:** {phase}
**Stealth mode:** {stealth_mode}

Consider:
- Target type and what parameters are most effective
- Previous scan results to avoid redundancy
- Stealth requirements (rate limiting, timing, evasion)
- Phase-appropriate depth (discovery = broad, exploitation = targeted)

Return optimized tool_args dict, timeout, and brief notes explaining your choices."""


@register_agent
class ParameterTunerAgent(Agent[TunerInput, TunerOutput]):
    """Tunes security tool parameters based on target and context."""

    role: ClassVar[AgentRole] = AgentRole.PARAMETER_TUNER
    name: ClassVar[str] = "ParameterTunerAgent"
    description: ClassVar[str] = "Tunes security tool parameters based on target and context"

    @staticmethod
    def is_complex_tool(tool_name: str) -> bool:
        """Check if a tool has a complex enough parameter space to benefit from tuning."""
        return tool_name.lower() in COMPLEX_TOOLS

    async def execute(
        self,
        context: AgentContext,
        input_data: TunerInput,
    ) -> AgentResult:
        """Generate optimized tool parameters."""
        try:
            task_text = TUNER_PROMPT.format(
                tool_name=input_data.tool_name,
                target=input_data.target,
                target_type=input_data.target_type,
                phase=input_data.phase,
                stealth_mode="Yes" if input_data.stealth_mode else "No",
            )

            # Include domain knowledge for the specific tool
            tool_knowledge = TOOL_KNOWLEDGE.get(input_data.tool_name.lower(), "")

            # Summarize previous results
            prev_summary = ""
            if input_data.previous_results:
                prev_lines = []
                for r in input_data.previous_results[:5]:
                    tool = r.get("tool", "unknown")
                    findings = r.get("findings_count", 0)
                    prev_lines.append(f"- {tool}: {findings} findings")
                prev_summary = "Previous scan results:\n" + "\n".join(prev_lines)

            ctx_mgr = ContextManager(max_context_tokens=3000)
            prompt = ctx_mgr.build(
                [
                    ContextSection("task", task_text, Priority.CRITICAL),
                    ContextSection(
                        "tool_knowledge",
                        f"**Tool Reference:**\n{tool_knowledge}" if tool_knowledge else "",
                        Priority.HIGH,
                        max_tokens=500,
                    ),
                    ContextSection(
                        "previous_results",
                        prev_summary,
                        Priority.MEDIUM,
                        max_tokens=300,
                    ),
                ]
            )

            action = await self._llm_generate_structured(
                prompt=prompt,
                response_model=TunerOutput,
                system_prompt=self._build_system_prompt(context),
                temperature=0.2,
            )

            return AgentResult(
                success=True,
                action=action,
                metadata={"tool": input_data.tool_name},
            )

        except Exception as e:
            logger.error("ParameterTunerAgent failed: %s", e)
            return AgentResult(success=False, error=str(e))
