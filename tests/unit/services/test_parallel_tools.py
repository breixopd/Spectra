"""Tests for parallel tool execution."""

from spectra_platform.services.ai.agents.base import (
    AgentContext,
    ParallelToolAction,
    ToolAction,
)
from spectra_platform.services.ai.agents.tool_selector import ToolSelectorAgent

PARALLEL_TOOL_GROUPS = ToolSelectorAgent.PARALLEL_TOOL_GROUPS  # type: ignore[attr-defined]


def test_parallel_tool_action_model():
    """ParallelToolAction serializes correctly."""
    tools = [
        ToolAction(
            tool_name="nmap",
            target="10.0.0.1",
            confidence=0.8,
            reasoning="recon",
        ),
        ToolAction(
            tool_name="naabu",
            target="10.0.0.1",
            confidence=0.8,
            reasoning="recon",
        ),
    ]
    action = ParallelToolAction(
        tools=tools,
        max_concurrency=2,
        confidence=0.85,
        reasoning="parallel recon",
    )

    data = action.model_dump()
    assert data["action_type"] == "run_tools_parallel"
    assert len(data["tools"]) == 2
    assert data["max_concurrency"] == 2
    assert data["tools"][0]["tool_name"] == "nmap"


def test_parallel_tool_groups_exist():
    """PARALLEL_TOOL_GROUPS has expected keys."""
    expected_keys = {
        "initial_recon",
        "web_fingerprint",
        "web_directory",
        "subdomain_enum",
        "web_vuln_scan",
        "smb_enum",
    }
    assert expected_keys.issubset(set(PARALLEL_TOOL_GROUPS.keys()))


def test_parallel_groups_have_multiple_tools():
    """Each group has >= 2 tools."""
    for group_name, tools in PARALLEL_TOOL_GROUPS.items():
        assert len(tools) >= 2, f"Group '{group_name}' has only {len(tools)} tool(s)"


def test_should_parallelize_stealth_mode():
    """Returns False when stealth_mode=True."""
    from unittest.mock import MagicMock

    agent = ToolSelectorAgent.__new__(ToolSelectorAgent)
    agent.llm = MagicMock()

    ctx_stealth = AgentContext(mission_id="m1", stealth_mode=True)
    assert agent._should_parallelize(ctx_stealth) is False  # type: ignore[attr-defined]

    ctx_normal = AgentContext(mission_id="m1", stealth_mode=False)
    assert agent._should_parallelize(ctx_normal) is True  # type: ignore[attr-defined]


def test_parallel_action_max_concurrency():
    """ParallelToolAction defaults to max_concurrency=3."""
    tools = [
        ToolAction(tool_name="a", target="t", confidence=0.8, reasoning="r"),
        ToolAction(tool_name="b", target="t", confidence=0.8, reasoning="r"),
    ]
    action = ParallelToolAction(tools=tools, confidence=0.8, reasoning="r")
    assert action.max_concurrency == 3
