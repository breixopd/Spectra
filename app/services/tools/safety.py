"""
Safety check logic for tool execution.

Handles safety supervisor checks, consensus validation,
and automatic command fixing for blocked commands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.safety import (
    SafetyAction,
    SafetyInput,
)

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.ai.agents.safety import SafetySupervisorAgent
    from app.services.ai.consensus import VotingSystem
    from app.services.mission.mission import Mission
    from app.services.tools.adapter import CommandToolAdapter

logger = logging.getLogger("spectra.tools.safety")

MAX_RETRIES = 2


async def perform_safety_check(
    safety_supervisor: SafetySupervisorAgent,
    mission: Mission,
    command: str,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Run the command through the Safety Supervisor."""
    safety_input = SafetyInput(
        command=command,
        tool_id=tool_name,
        target=target,
        args=args or {},
    )

    try:
        safety_context = AgentContext(
            mission_id=mission.id,
            session_id=mission.id,
            target=mission.target,
            mission=mission.directive,
            phase="safety_check",
            stealth_mode=False,
            max_concurrency=1,
        )

        safety_result = await safety_supervisor.execute(safety_context, safety_input)

        if safety_result.success and isinstance(safety_result.action, SafetyAction):
            if not safety_result.action.allowed:
                mission.log(f"[BLOCK] Safety check blocked: {safety_result.action.reason}")
                return False, safety_result.action.reason
        return True, "Safe"
    except Exception as e:
        mission.log(f"Safety check failed verification: {e}")
        return False, str(e)


async def perform_safety_check_with_retry(
    safety_supervisor: SafetySupervisorAgent,
    llm: Any,
    mission: Mission,
    command: str,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    builder: CommandToolAdapter,
    output_dir: Path,
    max_retries: int = MAX_RETRIES,
) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Run safety check with automatic command fixing on failure.

    Returns:
        Tuple of (is_safe, reason, fixed_args or None)
    """
    current_args = args
    current_command = command

    for attempt in range(max_retries + 1):
        is_safe, reason = await perform_safety_check(
            safety_supervisor, mission, current_command, tool_name, target, current_args
        )

        if is_safe:
            return True, "Safe", current_args if attempt > 0 else None

        if attempt < max_retries:
            mission.log(f"[ADAPT] Attempting to fix command (attempt {attempt + 1}/{max_retries})...")

            fixed_args = await _try_fix_command(llm, mission, tool_name, target, current_args, reason)

            if fixed_args is not None and fixed_args != current_args:
                current_args = fixed_args
                from app.services.tools.models import ToolExecutionRequest

                fixed_request = ToolExecutionRequest(
                    tool_id=tool_name,
                    target=target,
                    args=fixed_args,
                    timeout=None,
                )
                current_command = builder.builder.build_command(fixed_request, output_dir=str(output_dir))
                mission.log(f"[INFO] Retrying with fixed args: {fixed_args}")
            else:
                break

    return False, reason, None


async def perform_consensus_check(
    consensus: VotingSystem,
    mission: Mission,
    tool_name: str,
    risk_level: str,
) -> bool:
    """Get consensus for high-risk actions."""
    mission.log(f"[VOTE] High-risk action: {tool_name} ({risk_level})")

    from app.services.ai.agents.base import ActionRisk, AgentAction

    proxy_action = AgentAction(
        action_type="tool_execution",
        risk_level=ActionRisk.HIGH if risk_level == "high" else ActionRisk.CRITICAL,
        confidence=1.0,
        reasoning=f"Execute high-risk tool {tool_name}",
    )

    vote_result = await consensus.vote_on_action(
        proxy_action,
        {"target": mission.target, "tool": tool_name},
    )

    if vote_result.status != "approved":
        mission.log(f"[REJECTED] Action blocked by consensus: {vote_result.escalation_reason}")
        return False

    mission.log("[APPROVED] Action validated by consensus")
    return True


async def _try_fix_command(
    llm: Any,
    mission: Mission,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    error_reason: str,
) -> dict[str, Any] | None:
    """Use LLM to try to fix a blocked command."""
    try:
        from app.services.tools.registry import get_registry

        registry = get_registry()
        tool = registry.get_tool(tool_name)
        if not tool:
            return None

        prompt = f"""The following command was blocked by safety checks:
Tool: {tool_name}
Target: {target}
Arguments: {args}
Error: {error_reason}

Tool description: {tool.config.description}
Available arguments: {tool.config.execution.args_template}

Please provide ONLY a valid JSON object with corrected arguments that would fix the safety issue.
The arguments must be valid for this tool. Do not include any explanation, just the JSON.

Example response format:
{{"module": "exploit/unix/ftp/vsftpd_234_backdoor", "RHOSTS": "192.168.1.1"}}"""

        llm_response = await llm.generate(
            prompt=prompt,
            system_prompt="You are a security tool expert. Fix malformed commands by providing valid arguments as JSON.",
            temperature=0.1,
        )

        import json

        if hasattr(llm_response, "content"):
            response_text = llm_response.content
        elif hasattr(llm_response, "text"):
            response_text = llm_response.text
        else:
            response_text = str(llm_response)

        response_text = response_text.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(line for line in lines if not line.startswith("```"))

        fixed_args = json.loads(response_text)
        if isinstance(fixed_args, dict):
            mission.log(f"[INFO] LLM suggested fix: {fixed_args}")
            return fixed_args

    except Exception as e:
        logger.warning("Failed to fix command via LLM: %s", e)

    return None
