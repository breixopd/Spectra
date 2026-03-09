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
        key_logs = [entry for entry in input_data.logs[-50:] if any(k in entry for k in ["[OK]", "[ERROR]", "[SUCCESS]", "[FAIL]", "[APPROVED]", "[REJECTED]", "[LEARN]", "[ADAPT]"])]
        logs_text = "\n".join(key_logs[-20:]) if key_logs else "No significant log entries"

        base_prompt = """Analyze this completed penetration test and provide a comprehensive debrief.

Provide:
1. Executive summary (2-3 sentences on overall risk posture)
2. What worked well in this assessment
3. What failed or could be improved
4. What a human pentester would have done differently
5. Prioritized remediation recommendations for each finding type
6. Overall risk rating (critical/high/medium/low)
7. Suggested next steps for the target owner
8. Lessons learned for future assessments against similar targets"""

        target_section = f"""**Target:** {input_data.target}
**Directive:** {input_data.directive}
**Tools Used:** {', '.join(input_data.tools_run)}
**Total Findings:** {len(input_data.findings)}"""

        ctx = ContextManager(max_context_tokens=6000)
        prompt = ctx.build([
            ContextSection("task", base_prompt, Priority.CRITICAL),
            ContextSection("target", target_section, Priority.CRITICAL),
            ContextSection("findings", f"**Findings:**\n{findings_summary or 'No findings discovered'}", Priority.HIGH, max_tokens=1500),
            ContextSection("logs", f"**Key Events:**\n{logs_text}", Priority.MEDIUM, max_tokens=500),
            ContextSection("attack_surface", f"**Attack Surface:** {input_data.attack_surface_summary}", Priority.LOW, max_tokens=400),
            ContextSection("tools_run", f"**Tools Run:** {', '.join(input_data.tools_run)}", Priority.LOW, max_tokens=200),
        ])

        try:
            result = await self._llm_generate_structured(
                prompt=prompt,
                response_model=DebriefOutput,
                system_prompt="You are a senior penetration tester conducting a post-engagement debrief. Be specific, actionable, and honest about both successes and failures.",
                temperature=0.4,
            )
            return AgentResult(success=True, action=result)
        except Exception as e:
            logger.error("Debrief failed: %s", e)
            return AgentResult(success=False, error=str(e))
