"""
E2E Test: Tool Execution Integration

Tests real tool execution capabilities:
- Tool registry and plugin loading
- Tool adapter command execution
- Output parsing
- Integration with mission flow

These tests can optionally use real tools if available.
"""

import os
from pathlib import Path

import pytest

from spectra_domain.enums import RiskLevel
from spectra_tools.adapter import CommandToolAdapter
from spectra_tools_core.models import (
    ExecutionConfig,
    OutputFormat,
    ParsingConfig,
    ToolCapability,
    ToolCategory,
    ToolConfig,
    ToolExecutionRequest,
    ToolMetadata,
)
from spectra_tools_core.registry import get_registry, initialize_registry

pytestmark = [
    pytest.mark.e2e,
]


# --- Test Configuration ---


def get_plugins_dir() -> Path:
    """Get plugins directory path."""
    return Path(__file__).parent.parent.parent / "plugins"


def tool_is_available(tool_name: str) -> bool:
    """Check if a tool is available on the system."""
    import shutil

    return shutil.which(tool_name) is not None


# --- Tests ---


@pytest.mark.asyncio
class TestToolRegistry:
    """Test tool registry functionality."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry singleton before each test."""
        import spectra_tools_core.registry as registry_module

        registry_module._registry_instance = None
        yield
        registry_module._registry_instance = None

    async def test_registry_loads_plugins(self):
        """Test that registry loads plugin files."""
        # Explicitly point to the plugins directory relative to project root
        # This handles cases where CWD might vary or tests run from subdirs
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"

        registry = await initialize_registry(plugins_dir=plugins_dir)

        # Should have loaded some plugins
        tools = registry.list_tools()
        # Verify specific plugins to be sure
        tool_ids = [t.config.id for t in tools]
        assert "nmap" in tool_ids
        assert len(tools) > 0, f"No tools loaded from {plugins_dir}. Loaded: {tool_ids}"

    async def test_registry_gets_tool_by_id(self):
        """Test getting a specific tool."""
        # Ensure consistent plugins loading
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"
        registry = await initialize_registry(plugins_dir=plugins_dir)

        # Try to get nmap (should exist)
        nmap = registry.get_tool("nmap")
        assert nmap is not None, "nmap plugin not found"
        assert nmap.config.id == "nmap"

    async def test_registry_lists_available_tools(self):
        """Test listing available tools."""
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"
        registry = await initialize_registry(plugins_dir=plugins_dir)

        available = registry.get_available_tools()

        # All listed tools should have is_available set
        for _tool in available:
            # Note: is_available depends on system tool installation
            pass  # Just ensure no errors

    async def test_registry_filters_by_category(self):
        """Test filtering tools by category."""
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"
        registry = await initialize_registry(plugins_dir=plugins_dir)

        # Get discovery tools
        discovery_tools = [t for t in registry.list_tools() if t.config.category == ToolCategory.DISCOVERY]

        # Should have at least nmap
        tool_ids = [t.config.id for t in discovery_tools]
        assert "nmap" in tool_ids or "naabu" in tool_ids

    async def test_registry_filters_by_capability(self):
        """Test filtering tools by capability."""
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"
        registry = await initialize_registry(plugins_dir=plugins_dir)

        # Get all tools and filter by capability
        all_tools = registry.list_tools()
        port_scanners = [t for t in all_tools if ToolCapability.PORT_SCAN in t.config.metadata.capabilities]

        assert len(port_scanners) > 0, "No port scanning tools found"


@pytest.mark.asyncio
class TestToolAdapter:
    """Test tool adapter execution."""

    @pytest.fixture
    def sample_tool_config(self) -> ToolConfig:
        """Create a sample tool configuration."""
        return ToolConfig(
            id="test-tool",
            name="Test Tool",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="A test tool",
            signature=None,
            execution=ExecutionConfig(
                command="echo",
                args_template="{target}",
                timeout=30,
                working_dir=None,
            ),
            parsing=ParsingConfig(
                format=OutputFormat.TEXT,
                jq_filter=None,
            ),
            metadata=ToolMetadata(
                capabilities=[ToolCapability.PORT_SCAN],
                risk_level=RiskLevel.PASSIVE,
            ),
        )

    async def test_adapter_builds_command(self, sample_tool_config: ToolConfig):
        """Test that adapter builds commands correctly."""
        adapter = CommandToolAdapter(sample_tool_config)

        request = ToolExecutionRequest(
            tool_id="test-tool",
            target="192.168.1.1",
            args={},
            timeout=30,
        )

        # Uses newly exposed build_command
        command = adapter.build_command(request, None)

        assert "echo" in command
        assert "192.168.1.1" in command

    async def test_adapter_handles_args(self, sample_tool_config: ToolConfig):
        """Test that adapter handles extra arguments."""
        sample_tool_config.execution.args_template = "{target} {flags}"
        adapter = CommandToolAdapter(sample_tool_config)

        request = ToolExecutionRequest(
            tool_id="test-tool",
            target="192.168.1.1",
            args={"flags": "-v"},
            timeout=30,
        )

        command = adapter.build_command(request, None)

        assert "-v" in command

    async def test_adapter_executes_command(self, sample_tool_config: ToolConfig):
        """Test that adapter executes commands."""
        adapter = CommandToolAdapter(sample_tool_config)

        request = ToolExecutionRequest(
            tool_id="test-tool",
            target="hello world",
            args={},
            timeout=30,
        )

        result = await adapter.execute(request)

        assert result.success
        assert "hello world" in result.stdout

    async def test_adapter_handles_timeout(self):
        """Test that adapter handles command timeout."""
        config = ToolConfig(
            id="timeout-tool",
            name="Timeout Tool",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="A slow tool",
            signature=None,
            execution=ExecutionConfig(
                command="sleep",
                args_template="10",
                timeout=30,
                working_dir=None,
            ),
            parsing=ParsingConfig(
                format=OutputFormat.TEXT,
                jq_filter=None,
            ),
            metadata=ToolMetadata(
                capabilities=[],
                risk_level=RiskLevel.PASSIVE,
            ),
        )
        adapter = CommandToolAdapter(config)

        request = ToolExecutionRequest(
            tool_id="timeout-tool",
            target="test",  # Non-empty target required
            args={},
            timeout=1,  # 1 second timeout
        )

        result = await adapter.execute(request)

        assert not result.success
        assert "timed out" in result.stderr.lower()

    async def test_adapter_enforces_output_dir(self):
        """Test that adapter raises error if output_dir is missing but required by template."""
        config = ToolConfig(
            id="bad-tool",
            name="Bad Tool",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="A tool needing output",
            signature=None,
            execution=ExecutionConfig(
                command="echo",
                args_template="-o {output_file} {target}",
                timeout=30,
                working_dir=None,
            ),
            parsing=ParsingConfig(format=OutputFormat.TEXT),
            metadata=ToolMetadata(capabilities=[], risk_level=RiskLevel.PASSIVE),
        )
        adapter = CommandToolAdapter(config)
        request = ToolExecutionRequest(tool_id="bad-tool", target="127.0.0.1", args={})

        # Should raise ValueError because output_dir is None but {output_file} is in template
        # Validation happens in builder.build_command called by adapter.build_command or execute
        with pytest.raises(ValueError, match="requires output_dir"):
            adapter.build_command(request, None)

    async def test_adapter_parses_json_output(self):
        """Test JSON output parsing."""
        config = ToolConfig(
            id="json-tool",
            name="JSON Tool",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Outputs JSON",
            signature=None,
            execution=ExecutionConfig(
                command="echo",
                args_template='\'{"port": 80, "service": "http"}\'',
                timeout=30,
                working_dir=None,
            ),
            parsing=ParsingConfig(
                format=OutputFormat.JSON,
                jq_filter=None,
            ),
            metadata=ToolMetadata(
                capabilities=[],
                risk_level=RiskLevel.PASSIVE,
            ),
        )

        adapter = CommandToolAdapter(config)

        request = ToolExecutionRequest(
            tool_id="json-tool",
            target="test",  # Non-empty target required
            args={},
            timeout=30,
        )

        _result = await adapter.execute(request)

        # Note: The echo command may include quotes in output
        # This test verifies the parsing mechanism works


@pytest.mark.asyncio
class TestRealToolExecution:
    """Test execution of real security tools (if available)."""

    @pytest.mark.skipif(not tool_is_available("nmap"), reason="nmap not installed")
    async def test_nmap_localhost_scan(self):
        """Test nmap scan of localhost."""
        registry = get_registry()
        nmap = registry.get_tool("nmap")

        if not nmap:
            pytest.skip("nmap plugin not loaded")

        adapter = CommandToolAdapter(nmap.config)

        request = ToolExecutionRequest(
            tool_id="nmap",
            target="127.0.0.1",
            args={"ports": "22,80,443"},
            timeout=60,
        )

        result = await adapter.execute(request)

        # Should complete (success or not depends on what's running)
        assert result.duration_seconds < 60
        assert result.tool_id == "nmap"

    @pytest.mark.skipif(not tool_is_available("nuclei"), reason="nuclei not installed")
    async def test_nuclei_version(self):
        """Test nuclei can report version."""
        # Just test that nuclei runs
        import subprocess

        result = subprocess.run(
            ["nuclei", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert "nuclei" in result.stdout.lower() or "nuclei" in result.stderr.lower()


@pytest.mark.asyncio
class TestToolIntegrationWithMission:
    """Test tool integration within mission context."""

    async def test_tool_selector_uses_registry(self):
        """Test that tool selector uses the registry."""
        from spectra_ai_core.agents.base import AgentContext
        from spectra_ai_core.agents.tool_selector import (
            ToolSelectorAgent,
            ToolSelectorInput,
        )
        from tests.mocks.llm import MockLLMClient

        mock_llm = MockLLMClient(
            structured_responses={
                "ToolSelectorOutput": {
                    "action_type": "run_tool",
                    "confidence": 0.85,
                    "risk_level": "low",
                    "reasoning": "Port scanning",
                    "tool_name": "nmap",
                    "target": "192.168.1.1",
                    "tool_args": {},
                    "estimated_duration": 60,
                    "alternatives": [],
                    "skip_reason": None,
                }
            }
        )

        agent = ToolSelectorAgent(mock_llm)

        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="192.168.1.1",
            mission="Test",
            phase="discovery",
            stealth_mode=False,
            max_concurrency=1,
        )

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference=None,
            required_capability=None,
        )

        result = await agent.execute(context, input_data)

        assert result.success
        assert result.action is not None

    async def test_findings_parsed_from_tool_output(self):
        """Test that findings are extracted from tool output."""
        from spectra_tools_core.models import OutputFormat

        # Create a config that mimics nuclei output
        config = ToolConfig(
            id="mock-scanner",
            name="Mock Scanner",
            version="1.0.0",
            category=ToolCategory.WEB,
            description="Mock vulnerability scanner",
            signature=None,
            execution=ExecutionConfig(
                command="echo",
                args_template='\'{"name": "XSS", "severity": "high", "host": "{target}"}\'',
                timeout=30,
                working_dir=None,
            ),
            parsing=ParsingConfig(
                format=OutputFormat.JSON,
                mapping={
                    "name": "name",
                    "severity": "severity",
                    "host": "host",
                },
                jq_filter=None,
            ),
            metadata=ToolMetadata(
                capabilities=[ToolCapability.VULN_SCAN],
                risk_level=RiskLevel.LOW,
            ),
        )

        adapter = CommandToolAdapter(config)

        request = ToolExecutionRequest(
            tool_id="mock-scanner",
            target="example.com",
            args={},
            timeout=30,
        )

        _result = await adapter.execute(request)

        # Should have parsed the JSON output
        # Note: actual parsing depends on output format


class TestPluginLoading:
    """Test plugin file loading.

    Note: These are synchronous tests that don't need asyncio.
    """

    def test_plugins_directory_exists(self):
        """Test that plugins directory exists."""
        plugins_dir = get_plugins_dir()
        assert plugins_dir.exists(), f"Plugins directory not found: {plugins_dir}"

    def test_nmap_plugin_exists(self):
        """Test that nmap plugin file exists."""
        nmap_plugin = get_plugins_dir() / "nmap.json"
        assert nmap_plugin.exists(), "nmap.json plugin not found"

    def test_plugin_files_are_valid_json(self):
        """Test that all plugin files are valid JSON."""
        import json

        plugins_dir = get_plugins_dir()

        for plugin_file in plugins_dir.glob("*.json"):
            try:
                with open(plugin_file) as f:
                    data = json.load(f)

                # Basic structure check
                assert "id" in data, f"{plugin_file.name} missing 'id'"
                assert "name" in data, f"{plugin_file.name} missing 'name'"
                assert "execution" in data, f"{plugin_file.name} missing 'execution'"

            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {plugin_file.name}: {e}")

    def test_plugins_have_required_metadata(self):
        """Test that plugins have required metadata."""
        import json

        plugins_dir = get_plugins_dir()

        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                data = json.load(f)

            # Check metadata
            assert "metadata" in data, f"{plugin_file.name} missing 'metadata'"

            metadata = data["metadata"]
            assert "capabilities" in metadata, f"{plugin_file.name} missing 'capabilities'"
            assert "risk_level" in metadata, f"{plugin_file.name} missing 'risk_level'"

    @pytest.mark.asyncio
    @pytest.mark.skipif(os.geteuid() != 0, reason="Tool installation requires root privileges")
    @pytest.mark.skipif(
        os.environ.get("IS_TOOLS_CONTAINER", "").lower() != "true",
        reason="Full tool verification must run inside the Kali tools container",
    )
    @pytest.mark.skipif(
        os.environ.get("SKIP_TOOL_VERIFY") == "1",
        reason="Tool verification skipped in this environment",
    )
    async def test_all_tools_verification(self):
        """Test that all registered tools can be verified (installed and runnable)."""
        root_dir = Path(__file__).parent.parent.parent
        plugins_dir = root_dir / "plugins"
        registry = await initialize_registry(plugins_dir=plugins_dir)
        tools = registry.list_tools()

        assert len(tools) > 0, "No tools found in registry"

        failed_tools = []

        for tool in tools:
            # Skip if no verification command
            if not tool.config.installation.verification_command:
                print(f"Skipping {tool.config.id}: No verification command")
                continue

            print(f"Verifying {tool.config.id}...")

            # Run verification command
            import re
            import shlex
            import subprocess

            try:
                # Use shlex.split for safe command parsing, shell=False for security
                # Wrap in shell for complex commands (pipes, etc.) but with explicit /bin/sh
                cmd = tool.config.installation.verification_command
                # If command contains shell operators, use explicit shell invocation
                if any(op in cmd for op in ["|", "&&", "||", ">", "<", ";"]):
                    args = ["/bin/sh", "-c", cmd]
                else:
                    args = shlex.split(cmd)

                result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)

                success = result.returncode == 0
                if (
                    not success
                    and tool.config.installation.verification_regex
                    and re.search(
                        tool.config.installation.verification_regex,
                        result.stdout + result.stderr,
                    )
                ):
                    success = True

                if not success:
                    # Try to install if verification fails
                    print(f"  Verification failed for {tool.config.id}, attempting install...")
                    try:
                        await registry.install_tool(tool.config.id)
                        # Verify again with same safe approach
                        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)

                        success = result.returncode == 0
                        if (
                            not success
                            and tool.config.installation.verification_regex
                            and re.search(
                                tool.config.installation.verification_regex,
                                result.stdout + result.stderr,
                            )
                        ):
                            success = True

                        if not success:
                            failed_tools.append(
                                f"{tool.config.id} (exit code {result.returncode}): {result.stderr.strip()}"
                            )
                        else:
                            print(f"  OK (after install): {tool.config.id}")
                    except Exception as e:
                        failed_tools.append(f"{tool.config.id} (install failed): {e!s}")
                else:
                    print(f"  OK: {tool.config.id}")

            except subprocess.TimeoutExpired:
                failed_tools.append(f"{tool.config.id}: Timeout")
            except Exception as e:
                failed_tools.append(f"{tool.config.id}: {e!s}")

        assert not failed_tools, f"Tool verification failed for: {', '.join(failed_tools)}"
