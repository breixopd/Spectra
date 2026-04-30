from unittest.mock import AsyncMock

import pytest

from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
)
from spectra_tools_core.models import (
    RegisteredTool,
    ToolCapability,
    ToolCategory,
    ToolConfig,
    ToolStatus,
)


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def tool_selector(mock_llm):
    return ToolSelectorAgent(mock_llm)


@pytest.fixture
def mock_nmap_tool():
    config = ToolConfig(
        id="nmap",
        name="Nmap",
        description="Network Mapper",
        version="7.94.0",
        category=ToolCategory.DISCOVERY,
        execution={"command": "nmap", "timeout": 3600},
        metadata={"capabilities": [ToolCapability.PORT_SCAN], "risk_level": "medium"},
    )
    return RegisteredTool(config=config, status=ToolStatus.READY)


@pytest.mark.asyncio
async def test_stealth_mode_enforcement(tool_selector, mock_nmap_tool):
    """Test that stealth mode strictly overrides arguments."""
    AgentContext(
        mission_id="test-mission-1",
        session_id="test-session",
        stealth_mode=True,  # ENABLED
        phase="discovery",
    )

    # Simulate LLM returning aggressive arguments
    aggressive_args = {"-T": "4", "--min-rate": "1000", "port": "80"}

    # We test the internal method directly or we'd need to mock the registry
    # Let's test _apply_stealth_settings directly

    overridden_args = tool_selector._apply_stealth_settings(mock_nmap_tool, aggressive_args)

    # Assertions
    assert overridden_args["-T"] == "1"  # Should be forced to 1 (Paranoid)
    assert overridden_args["--scan-delay"] == "1s"
    assert (
        "-T4" not in overridden_args
    )  # Should strip aggressive flags keys if they were keys (bad dict usage but consistent with logic)
    # Note: In the implementation we pop "-T4" keys. In the input above "-T" is the key.
    # The current implementation handles both dict-style args and flags-as-keys slightly ambiguously,
    # but the key assertion is that specific stealth keys are SET.


@pytest.mark.asyncio
async def test_argument_validation_integers(tool_selector, mock_nmap_tool):
    """Test that arguments are validated and sanitized."""

    # Broken arguments (string for port)
    args = {
        "port": "80, 443",  # Spaces should be removed
        "rate": "fast",  # Should be removed as it's not an int
        "threads": "10",  # Should be converted to int
    }

    tool_selector._validate_tool_args(mock_nmap_tool, args)

    assert args["port"] == "80,443"
    assert "rate" not in args  # Should have been popped
    assert args["threads"] == 10  # Should be int
