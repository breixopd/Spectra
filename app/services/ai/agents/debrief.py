"""
Debrief Agent — Post-mission analysis and lessons learned.

Analyzes the full mission log after completion to generate:
- What worked and what didn't
- What a human pentester would have done differently
- Specific remediation recommendations per finding
- Risk prioritization based on business context
"""

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import Agent, AgentAction, AgentContext, AgentResult, AgentRole
from app.services.ai.agents.registry import register_agent
from app.services.ai.context import ContextManager, ContextSection, Priority

logger = logging.getLogger("spectra.ai.agents.debrief")


class DebriefInput(BaseModel):
    target: str
    directive: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    tools_run: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    attack_surface_summary: dict[str, Any] = Field(default_factory=dict)


class DebriefOutput(AgentAction):
    action_type: str = "debrief"
    executive_summary: str = ""
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    human_comparison: str = ""  # what a human pentester would do differently
    remediation_priorities: list[dict[str, str]] = Field(default_factory=list)  # [{finding, priority, recommendation}]
    lessons_learned: list[str] = Field(default_factory=list)
    risk_rating: str = "medium"  # critical, high, medium, low
    next_steps: list[str] = Field(default_factory=list)


@register_agent
class DebriefAgent(Agent[DebriefInput, DebriefOutput]):
    role: ClassVar[AgentRole] = AgentRole.DEBRIEF
    name: ClassVar[str] = "DebriefAgent"
    description: ClassVar[str] = "Analyzes completed missions to extract lessons learned and remediation priorities"

    async def execute(self, context: AgentContext, input_data: DebriefInput) -> AgentResult:
        # Build a summary of the mission for the LLM
        findings_summary = ""
        for f in input_data.findings[:20]:
            sev = f.get("severity", "info")
            name = f.get("name") or f.get("title") or f.get("template-id", "Unknown")
            count = f.get("count", 1)
            findings_summary += f"- [{sev.upper()}] {name}" + (f" (x{count})" if count > 1 else "") + "\n"

        # Key log entries only
        key_logs = [
            entry
            for entry in input_data.logs[-50:]
            if any(
                k in entry
                for k in ["[OK]", "[ERROR]", "[SUCCESS]", "[FAIL]", "[APPROVED]", "[REJECTED]", "[LEARN]", "[ADAPT]"]
            )
        ]
        logs_text = "\n".join(key_logs[-20:]) if key_logs else "No significant log entries"

        base_prompt = """You are a **Senior Penetration Test Lead** conducting a PTES-aligned post-engagement debrief.

Your role:
- Objectively evaluate the assessment's effectiveness
- Provide actionable remediation guidance ranked by business risk
- Compare automated results to what an experienced human pentester would achieve
- Identify gaps in coverage and suggest follow-up assessments

**Instructions — produce each section below:**

1. **executive_summary**: 2-3 sentences on overall risk posture. Include counts of critical/high/medium/low findings and the single most impactful issue.
2. **what_worked**: List specific techniques, tools, or scan strategies that produced meaningful results.
3. **what_failed**: List tools that returned no results, scans that timed out, or attack paths that were blocked.
4. **human_comparison**: Describe what a seasoned human pentester would do differently — e.g., manual testing, social engineering, physical access, chained exploits the automation missed.
5. **remediation_priorities**: For each distinct finding category, provide:
   - `finding`: short title
   - `priority`: "critical" | "high" | "medium" | "low"
   - `recommendation`: specific, actionable fix (not generic advice)
6. **risk_rating**: Overall rating — "critical" if any RCE/auth-bypass exists, "high" if multiple exploitable vulns, "medium" if only info-disclosure / misconfigs, "low" if only informational.
7. **next_steps**: Concrete actions for the target owner (patch X, retest Y, engage red-team for Z).
8. **lessons_learned**: What the *assessment team* should improve next time.

**Output format:** JSON matching the DebriefOutput schema.

---
**Few-shot example (abbreviated):**

Input:
  Target: 10.0.0.5
  Directive: Full external assessment
  Tools: nmap, nuclei, nikto, sqlmap
  Findings: [CRITICAL] SQLi in /login, [HIGH] Outdated Apache 2.4.25, [MEDIUM] Missing CSP header

Expected output:
```json
{{
  "executive_summary": "The target has a CRITICAL SQL injection in the login form allowing full database access, compounded by an outdated Apache with known CVEs. Immediate patching and input validation are required.",
  "what_worked": ["nmap quickly identified open ports and service versions", "nuclei detected the outdated Apache CVE", "sqlmap confirmed exploitable blind SQLi"],
  "what_failed": ["nikto produced mostly false-positive informational findings", "directory brute-force yielded no new endpoints"],
  "human_comparison": "A human pentester would chain the SQLi to extract credentials, pivot to admin panel access, and attempt OS command execution — testing the full kill chain rather than stopping at database access confirmation.",
  "remediation_priorities": [
    {{"finding": "SQL Injection in /login", "priority": "critical", "recommendation": "Use parameterized queries / prepared statements in the login handler. Deploy a WAF rule as immediate mitigation."}},
    {{"finding": "Apache 2.4.25 CVE-2017-7679", "priority": "high", "recommendation": "Upgrade Apache to latest 2.4.x stable release."}},
    {{"finding": "Missing CSP Header", "priority": "medium", "recommendation": "Add Content-Security-Policy header with script-src 'self'."}}  ],
  "risk_rating": "critical",
  "next_steps": ["Patch SQLi immediately", "Upgrade Apache within 7 days", "Schedule retest after remediation"],
  "lessons_learned": ["Run sqlmap earlier when login forms are discovered", "Skip nikto on modern stacks — nuclei covers it better"]
}}
```"""

        target_section = f"""**Target:** {input_data.target}
**Directive:** {input_data.directive}
**Tools Used:** {", ".join(input_data.tools_run)}
**Total Findings:** {len(input_data.findings)}"""

        ctx = ContextManager(max_context_tokens=6000)
        prompt = ctx.build(
            [
                ContextSection("task", base_prompt, Priority.CRITICAL),
                ContextSection("target", target_section, Priority.CRITICAL),
                ContextSection(
                    "findings",
                    f"**Findings:**\n{findings_summary or 'No findings discovered'}",
                    Priority.HIGH,
                    max_tokens=1500,
                ),
                ContextSection("logs", f"**Key Events:**\n{logs_text}", Priority.MEDIUM, max_tokens=500),
                ContextSection(
                    "attack_surface",
                    f"**Attack Surface:** {input_data.attack_surface_summary}",
                    Priority.LOW,
                    max_tokens=400,
                ),
                ContextSection(
                    "tools_run", f"**Tools Run:** {', '.join(input_data.tools_run)}", Priority.LOW, max_tokens=200
                ),
            ]
        )

        try:
            result = await self._llm_generate_structured(
                prompt=prompt,
                response_model=DebriefOutput,
                system_prompt="You are a senior penetration tester conducting a PTES-aligned post-engagement debrief. Be specific and actionable. Ground every statement in evidence from the findings and logs — do not speculate. Be honest about both successes and failures.",
                temperature=0.4,
            )
            return AgentResult(success=True, action=result)
        except Exception as e:
            logger.error("Debrief failed: %s", e)
            return AgentResult(success=False, error=str(e))
