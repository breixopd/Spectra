from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai_core.agents.safety import SafetyAction
from spectra_tools.safety_checks import (
    _try_fix_command,
    perform_safety_check,
    perform_safety_check_with_retry,
)


@pytest.mark.asyncio
async def test_perform_safety_check_safe():
    mission = MagicMock()
    mission.target = "1.2.3.4"
    mission.id = "m1"
    mission.user_id = "u1"
    mission.directive = "test"
    mission.log = MagicMock()

    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(allowed=True, reason="", confidence=1.0, reasoning="safe")

    supervisor = AsyncMock()
    supervisor.execute = AsyncMock(return_value=safety_result)

    is_safe, reason = await perform_safety_check(mission, "nmap 1.2.3.4", "nmap", "1.2.3.4", {}, supervisor)
    assert is_safe is True
    assert reason == "Safe"


@pytest.mark.asyncio
async def test_perform_safety_check_blocked():
    mission = MagicMock()
    mission.target = "1.2.3.4"
    mission.id = "m1"
    mission.user_id = "u1"
    mission.directive = "test"
    mission.log = MagicMock()

    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(allowed=False, reason="out of scope", confidence=1.0, reasoning="unsafe")

    supervisor = AsyncMock()
    supervisor.execute = AsyncMock(return_value=safety_result)

    is_safe, reason = await perform_safety_check(mission, "nmap 1.2.3.4", "nmap", "1.2.3.4", {}, supervisor)
    assert is_safe is False
    assert reason == "out of scope"
    mission.log.assert_any_call("[BLOCK] Safety check blocked: out of scope")


@pytest.mark.asyncio
async def test_perform_safety_check_exception():
    mission = MagicMock()
    mission.target = "1.2.3.4"
    mission.id = "m1"
    mission.user_id = "u1"
    mission.directive = "test"
    mission.log = MagicMock()

    supervisor = AsyncMock()
    supervisor.execute = AsyncMock(side_effect=RuntimeError("boom"))

    is_safe, reason = await perform_safety_check(mission, "nmap 1.2.3.4", "nmap", "1.2.3.4", {}, supervisor)
    assert is_safe is False
    assert "boom" in reason


@pytest.mark.asyncio
async def test_perform_safety_check_with_retry_safe_first_try():
    mission = MagicMock()
    mission.target = "1.2.3.4"
    mission.id = "m1"
    mission.user_id = "u1"
    mission.directive = "test"
    mission.log = MagicMock()

    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(allowed=True, reason="", confidence=1.0, reasoning="safe")

    supervisor = AsyncMock()
    supervisor.execute = AsyncMock(return_value=safety_result)

    builder = MagicMock()

    is_safe, _reason, fixed_args = await perform_safety_check_with_retry(
        mission, "nmap 1.2.3.4", "nmap", "1.2.3.4", {}, builder, "/tmp", supervisor, AsyncMock(), max_retries=2
    )
    assert is_safe is True
    assert fixed_args is None


@pytest.mark.asyncio
async def test_perform_safety_check_with_retry_fixes():
    mission = MagicMock()
    mission.target = "1.2.3.4"
    mission.id = "m1"
    mission.user_id = "u1"
    mission.directive = "test"
    mission.log = MagicMock()

    block_result = MagicMock()
    block_result.success = True
    block_result.action = SafetyAction(allowed=False, reason="out of scope", confidence=1.0, reasoning="unsafe")

    safe_result = MagicMock()
    safe_result.success = True
    safe_result.action = SafetyAction(allowed=True, reason="", confidence=1.0, reasoning="safe")

    supervisor = AsyncMock()
    supervisor.execute = AsyncMock(side_effect=[block_result, safe_result])

    builder = MagicMock()
    builder.builder.build_command.return_value = "nmap --safe 1.2.3.4"

    llm_client = AsyncMock()

    with patch("spectra_tools.safety_checks._try_fix_command", new_callable=AsyncMock, return_value={"--safe": True}):
        is_safe, _reason, fixed_args = await perform_safety_check_with_retry(
            mission, "nmap 1.2.3.4", "nmap", "1.2.3.4", {}, builder, "/tmp", supervisor, llm_client, max_retries=2
        )

    assert is_safe is True
    assert fixed_args == {"--safe": True}


@pytest.mark.asyncio
async def test_try_fix_command_no_tool():
    mission = MagicMock()
    mission.log = MagicMock()

    registry = MagicMock()
    registry.get_tool.return_value = None

    llm_client = AsyncMock()

    with patch("spectra_tools_core.registry.get_registry", return_value=registry):
        result = await _try_fix_command(mission, "nmap", "1.2.3.4", {}, "error", llm_client)

    assert result is None


@pytest.mark.asyncio
async def test_try_fix_command_success():
    mission = MagicMock()
    mission.log = MagicMock()

    tool = MagicMock()
    tool.config.description = "port scanner"
    tool.config.execution.args_template = {"target": "str"}

    registry = MagicMock()
    registry.get_tool.return_value = tool

    llm_response = MagicMock()
    llm_response.content = '{"target": "1.2.3.4"}'

    llm_client = AsyncMock()
    llm_client.generate = AsyncMock(return_value=llm_response)

    with patch("spectra_tools_core.registry.get_registry", return_value=registry):
        result = await _try_fix_command(mission, "nmap", "1.2.3.4", {}, "error", llm_client)

    assert result == {"target": "1.2.3.4"}


@pytest.mark.asyncio
async def test_try_fix_command_invalid_json():
    mission = MagicMock()
    mission.log = MagicMock()

    tool = MagicMock()
    tool.config.description = "port scanner"
    tool.config.execution.args_template = {"target": "str"}

    registry = MagicMock()
    registry.get_tool.return_value = tool

    llm_response = MagicMock()
    llm_response.content = "not json"

    llm_client = AsyncMock()
    llm_client.generate = AsyncMock(return_value=llm_response)

    with patch("spectra_tools_core.registry.get_registry", return_value=registry):
        result = await _try_fix_command(mission, "nmap", "1.2.3.4", {}, "error", llm_client)

    assert result is None


@pytest.mark.asyncio
async def test_try_fix_command_code_block():
    mission = MagicMock()
    mission.log = MagicMock()

    tool = MagicMock()
    tool.config.description = "port scanner"
    tool.config.execution.args_template = {"target": "str"}

    registry = MagicMock()
    registry.get_tool.return_value = tool

    llm_response = MagicMock()
    llm_response.content = '```json\n{"target": "1.2.3.4"}\n```'

    llm_client = AsyncMock()
    llm_client.generate = AsyncMock(return_value=llm_response)

    with patch("spectra_tools_core.registry.get_registry", return_value=registry):
        result = await _try_fix_command(mission, "nmap", "1.2.3.4", {}, "error", llm_client)

    assert result == {"target": "1.2.3.4"}
