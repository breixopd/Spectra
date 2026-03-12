"""
Tests for ToolRegistry operations.

Covers: list_tools, get_tool, get_available_tools, get_tools_by_category,
add_plugin, remove_plugin, _save_plugin, validate_plugin,
list_tools_for_ai, get_tool_for_ai.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.models import (
    ExecutionConfig,
    RegisteredTool,
    ToolConfig,
    ToolStatus,
)
from app.services.tools.registry import ToolRegistry
from app.services.tools.registry.exceptions import PluginValidationError

# --- Helpers ---


def _make_config(
    tool_id: str,
    name: str = "Test Tool",
    category: str = "discovery",
    is_system: bool = False,
    version: str = "1.0.0",
) -> ToolConfig:
    """Create a minimal valid ToolConfig."""
    return ToolConfig(
        id=tool_id,
        name=name,
        version=version,
        category=category,
        description=f"{name} description",
        execution=ExecutionConfig(command=tool_id, args_template="-t {target}"),
        is_system=is_system,
    )


def _make_tool(
    tool_id: str,
    status: ToolStatus = ToolStatus.READY,
    is_system: bool = False,
    category: str = "discovery",
) -> RegisteredTool:
    """Create a RegisteredTool with given status."""
    config = _make_config(
        tool_id, name=tool_id.title(), category=category, is_system=is_system
    )
    return RegisteredTool(config=config, status=status)


# --- Fixtures ---


@pytest.fixture
def registry(tmp_path):
    """Create a ToolRegistry with temp plugins dir and safe_mode=False."""
    reg = ToolRegistry(plugins_dir=tmp_path, safe_mode=False)

    # Pre-populate with test tools
    reg._tools["nmap"] = _make_tool("nmap", ToolStatus.READY)
    reg._tools["hydra"] = _make_tool("hydra", ToolStatus.READY, category="exploitation")
    reg._tools["nikto"] = _make_tool("nikto", ToolStatus.PENDING, category="web")
    reg._tools["builtin"] = _make_tool("builtin", ToolStatus.READY, is_system=True)

    return reg


# ===========================
# list_tools
# ===========================


class TestListTools:
    def test_returns_all_tools(self, registry):
        tools = registry.list_tools()
        assert len(tools) == 4
        ids = {t.config.id for t in tools}
        assert ids == {"nmap", "hydra", "nikto", "builtin"}

    def test_returns_empty_when_no_tools(self, tmp_path):
        reg = ToolRegistry(plugins_dir=tmp_path, safe_mode=False)
        assert reg.list_tools() == []


# ===========================
# get_tool
# ===========================


class TestGetTool:
    def test_valid_id(self, registry):
        tool = registry.get_tool("nmap")
        assert tool is not None
        assert tool.config.id == "nmap"

    def test_invalid_id(self, registry):
        assert registry.get_tool("nonexistent") is None

    def test_case_insensitive_lookup(self, registry):
        """get_tool falls back to lowercased lookup."""
        tool = registry.get_tool("Nmap")
        # The fallback tries tool_id.lower() which is "nmap"
        assert tool is not None
        assert tool.config.id == "nmap"

    def test_completely_wrong_case(self, registry):
        """When even lowercase doesn't match, returns None."""
        assert registry.get_tool("ZZZZ") is None


# ===========================
# get_available_tools
# ===========================


class TestGetAvailableTools:
    def test_filters_ready_only(self, registry):
        available = registry.get_available_tools()
        ids = {t.config.id for t in available}
        assert "nmap" in ids
        assert "hydra" in ids
        assert "builtin" in ids
        assert "nikto" not in ids  # PENDING, not READY

    def test_empty_if_none_ready(self, tmp_path):
        reg = ToolRegistry(plugins_dir=tmp_path, safe_mode=False)
        reg._tools["a"] = _make_tool("aa", ToolStatus.PENDING)
        reg._tools["b"] = _make_tool("bb", ToolStatus.FAILED)
        assert reg.get_available_tools() == []


# ===========================
# get_tools_by_category
# ===========================


class TestGetToolsByCategory:
    def test_filters_by_category(self, registry):
        discovery = registry.get_tools_by_category("discovery")
        ids = {t.config.id for t in discovery}
        assert "nmap" in ids
        assert "builtin" in ids  # default category is discovery
        assert "hydra" not in ids

    def test_exploitation_category(self, registry):
        exploit = registry.get_tools_by_category("exploitation")
        assert len(exploit) == 1
        assert exploit[0].config.id == "hydra"

    def test_unknown_category_returns_empty(self, registry):
        assert registry.get_tools_by_category("unknown_cat") == []


# ===========================
# add_plugin
# ===========================


class TestAddPlugin:
    @pytest.mark.asyncio
    async def test_adds_new_tool(self, registry):
        new_data = {
            "id": "sqlmap",
            "name": "SQLMap",
            "version": "2.0.0",
            "category": "web",
            "description": "SQL injection tool",
            "execution": {"command": "sqlmap", "args_template": "-u {target}"},
        }
        result = await registry.add_plugin(new_data)

        assert result.config.id == "sqlmap"
        assert result.status == ToolStatus.PENDING
        assert "sqlmap" in registry._tools

    @pytest.mark.asyncio
    async def test_overwrites_existing_non_system(self, registry):
        updated_data = {
            "id": "nmap",
            "name": "Nmap Updated",
            "version": "2.0.0",
            "category": "discovery",
            "description": "Updated nmap",
            "execution": {"command": "nmap", "args_template": "-sV {target}"},
        }
        result = await registry.add_plugin(updated_data)

        assert result.config.name == "Nmap Updated"
        assert result.status == ToolStatus.PENDING

    @pytest.mark.asyncio
    async def test_rejects_system_tool_overwrite(self, registry):
        system_data = {
            "id": "builtin",
            "name": "Builtin Override",
            "version": "1.0.0",
            "category": "discovery",
            "description": "Should fail",
            "execution": {"command": "builtin", "args_template": ""},
        }
        with pytest.raises(PluginValidationError, match="Cannot overwrite system tool"):
            await registry.add_plugin(system_data)


# ===========================
# remove_plugin
# ===========================


class TestRemovePlugin:
    @pytest.mark.asyncio
    async def test_removes_tool(self, registry):
        result = await registry.remove_plugin("nmap")
        assert result is True
        assert "nmap" not in registry._tools

    @pytest.mark.asyncio
    async def test_rejects_system_tool(self, registry):
        result = await registry.remove_plugin("builtin")
        assert result is False
        assert "builtin" in registry._tools

    @pytest.mark.asyncio
    async def test_rejects_unknown_tool(self, registry):
        result = await registry.remove_plugin("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_rejects_invalid_id_format(self, registry):
        result = await registry.remove_plugin("../../etc/passwd")
        assert result is False

    @pytest.mark.asyncio
    async def test_removes_plugin_file(self, registry, tmp_path):
        """When a plugin file exists on disk, it is deleted."""
        plugin_file = tmp_path / "hydra.json"
        plugin_file.write_text("{}")

        result = await registry.remove_plugin("hydra")
        assert result is True
        assert not plugin_file.exists()


# ===========================
# _save_plugin
# ===========================


class TestSavePlugin:
    @pytest.mark.asyncio
    async def test_writes_to_disk(self, registry, tmp_path):
        config = _make_config("new-tool", name="New Tool")

        with patch("app.services.tools.registry.registry.aiofiles.open") as mock_aiofiles:
            mock_file = AsyncMock()
            mock_aiofiles.return_value.__aenter__ = AsyncMock(return_value=mock_file)
            mock_aiofiles.return_value.__aexit__ = AsyncMock(return_value=False)

            # We also need to mock Path.rename
            with patch.object(type(tmp_path / ".new-tool.json.tmp"), "rename"):
                await registry._save_plugin(config)

            mock_aiofiles.assert_called_once()
            mock_file.write.assert_called()

    @pytest.mark.asyncio
    async def test_rejects_invalid_id_for_filesystem(self, registry):
        config = _make_config("nmap")
        config.id = "../../bad"  # bypass pydantic by direct assignment

        with pytest.raises(ValueError, match="Invalid tool ID for filesystem"):
            await registry._save_plugin(config)

    @pytest.mark.asyncio
    async def test_creates_plugins_dir(self, tmp_path):
        nested_dir = tmp_path / "subdir" / "plugins"
        reg = ToolRegistry(plugins_dir=nested_dir, safe_mode=False)
        config = _make_config("test-tool")

        with patch("app.services.tools.registry.registry.aiofiles.open") as mock_aiofiles:
            mock_file = AsyncMock()
            mock_aiofiles.return_value.__aenter__ = AsyncMock(return_value=mock_file)
            mock_aiofiles.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(type(nested_dir / ".test-tool.json.tmp"), "rename"):
                await reg._save_plugin(config)

        assert nested_dir.exists()


# ===========================
# validate_plugin
# ===========================


class TestValidatePlugin:
    def test_delegates_to_validator(self, registry):
        data = {"some": "data"}
        mock_config = _make_config("validated")
        registry.validator.validate_plugin = MagicMock(return_value=mock_config)

        result = registry.validate_plugin(data)

        registry.validator.validate_plugin.assert_called_once_with(data)
        assert result.id == "validated"


# ===========================
# list_tools_for_ai
# ===========================


class TestListToolsForAI:
    def test_returns_correct_format(self, registry):
        ai_tools = registry.list_tools_for_ai()
        # Only READY tools
        ids = {t["id"] for t in ai_tools}
        assert "nmap" in ids
        assert "hydra" in ids
        assert "builtin" in ids
        assert "nikto" not in ids  # PENDING

    def test_dict_has_expected_keys(self, registry):
        ai_tools = registry.list_tools_for_ai()
        for tool_dict in ai_tools:
            assert "id" in tool_dict
            assert "name" in tool_dict
            assert "description" in tool_dict
            assert "category" in tool_dict
            assert "command" in tool_dict
            assert "summary" in tool_dict

    def test_empty_when_none_available(self, tmp_path):
        reg = ToolRegistry(plugins_dir=tmp_path, safe_mode=False)
        assert reg.list_tools_for_ai() == []


# ===========================
# get_tool_for_ai
# ===========================


class TestGetToolForAI:
    def test_returns_dict_for_ready_tool(self, registry):
        result = registry.get_tool_for_ai("nmap")
        assert result is not None
        assert result["id"] == "nmap"
        assert "command" in result

    def test_returns_none_for_pending_tool(self, registry):
        result = registry.get_tool_for_ai("nikto")
        assert result is None

    def test_returns_none_for_unknown_tool(self, registry):
        result = registry.get_tool_for_ai("nonexistent")
        assert result is None
