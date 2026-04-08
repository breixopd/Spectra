"""Safety checks for tool execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.safety import SafetyAction, SafetyInput
from app.services.tools.models import ToolExecutionRequest

if TYPE_CHECKING:
    from app.services.ai.agents.safety import SafetySupervisorAgent
    from app.services.ai.llm import LLMClient
    from app.services.mission.mission import Mission
    from app.services.tools.adapter import CommandToolAdapter

logger = logging.getLogger(__name__)


async def perform_safety_check(
    mission: Mission,
    command: str,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    safety_supervisor: SafetySupervisorAgent,
) -> tuple[bool, str]:
    """Run the command through the Safety Supervisor."""
    scope_targets = [mission.target] if mission.target else []
    safety_input = SafetyInput(
        command=command,
        tool_id=tool_name,
        target=target,
        args=args or {},
        scope_targets=scope_targets,
    )

    try:
        safety_context = AgentContext(
            mission_id=mission.id,
            session_id=mission.id,
            user_id=mission.user_id,
            target=mission.target,
            mission=mission.directive,
            phase="safety_check",
            stealth_mode=False,
            max_concurrency=1,
            extra_context="",
            cost_tracker=None,
        )

        safety_result = await safety_supervisor.execute(safety_context, safety_input)

        if (
            safety_result.success
            and isinstance(safety_result.action, SafetyAction)
            and not safety_result.action.allowed
        ):
            mission.log(f"[BLOCK] Safety check blocked: {safety_result.action.reason}")
            return False, safety_result.action.reason
        return True, "Safe"
    except (OSError, RuntimeError, ValueError, TimeoutError) as e:
        mission.log(f"Safety check failed verification: {e}")
        return False, str(e)


async def perform_safety_check_with_retry(
    mission: Mission,
    command: str,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    builder: CommandToolAdapter,
    output_dir,
    safety_supervisor: SafetySupervisorAgent,
    llm_client: LLMClient,
    max_retries: int = 2,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Run safety check with automatic command fixing on failure."""
    current_args = args
    current_command = command

    for attempt in range(max_retries + 1):
        is_safe, reason = await perform_safety_check(
            mission,
            current_command,
            tool_name,
            target,
            current_args,
            safety_supervisor,
        )

        if is_safe:
            return True, "Safe", current_args if attempt > 0 else None

        if attempt < max_retries:
            mission.log(f"[ADAPT] Attempting to fix command (attempt {attempt + 1}/{max_retries})...")

            fixed_args = await _try_fix_command(
                mission,
                tool_name,
                target,
                current_args,
                reason,
                llm_client,
            )

            if fixed_args is not None and fixed_args != current_args:
                current_args = fixed_args
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


async def _try_fix_command(
    mission: Mission,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    error_reason: str,
    llm_client: LLMClient,
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

        llm_response = await llm_client.generate(
            prompt=prompt,
            system_prompt="You are a security tool expert. Fix malformed commands by providing valid arguments as JSON.",
            temperature=0.1,
        )

        import json

        response_text = llm_response.content if hasattr(llm_response, "content") else str(llm_response)

        response_text = response_text.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(line for line in lines if not line.startswith("```"))

        fixed_args = json.loads(response_text)
        if isinstance(fixed_args, dict):
            mission.log(f"[INFO] LLM suggested fix: {fixed_args}")
            return fixed_args

    except (OSError, RuntimeError, ValueError, TimeoutError) as e:
        logger.warning("Failed to fix command via LLM: %s", e)

    return None
