from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import jsonschema
except ImportError:
    jsonschema = None

from spectra_tools.validation import validate_and_resolve_tool


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_invalid_name():
    mission = MagicMock()
    mission.log = MagicMock()

    tool, error = await validate_and_resolve_tool(mission, "bad_name!", "1.2.3.4", {})
    assert tool is None
    assert error is not None
    assert "Invalid tool name" in error.stderr


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_not_found():
    mission = MagicMock()
    mission.log = MagicMock()

    mock_registry = MagicMock()
    mock_registry.sync_status_from_cache = AsyncMock()
    mock_registry.get_tool.return_value = None

    with patch("spectra_tools.validation.get_registry", return_value=mock_registry):
        tool, error = await validate_and_resolve_tool(mission, "nmap", "1.2.3.4", {})

    assert tool is None
    assert "not available" in error.stderr


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_not_installed():
    mission = MagicMock()
    mission.log = MagicMock()

    mock_tool = MagicMock()
    mock_tool.is_available = False
    mock_tool.config.execution.args_schema = None

    mock_registry = MagicMock()
    mock_registry.sync_status_from_cache = AsyncMock()
    mock_registry.get_tool.return_value = mock_tool

    with patch("spectra_tools.validation.get_registry", return_value=mock_registry):
        tool, error = await validate_and_resolve_tool(mission, "nmap", "1.2.3.4", {})

    assert tool == mock_tool
    assert error is None
    mission.log.assert_called_with("Tool nmap readiness is pending; worker will verify the installed binary before execution")


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_already_available():
    mission = MagicMock()
    mission.log = MagicMock()

    mock_tool = MagicMock()
    mock_tool.is_available = True
    mock_tool.config.execution.args_schema = None

    mock_registry = MagicMock()
    mock_registry.sync_status_from_cache = AsyncMock()
    mock_registry.get_tool.return_value = mock_tool

    with patch("spectra_tools.validation.get_registry", return_value=mock_registry):
        tool, error = await validate_and_resolve_tool(mission, "nmap", "1.2.3.4", {})

    assert tool == mock_tool
    assert error is None


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_jsonschema_invalid():
    mission = MagicMock()
    mission.log = MagicMock()

    mock_tool = MagicMock()
    mock_tool.is_available = True
    mock_tool.config.execution.args_schema = {"type": "object", "required": ["target"]}

    mock_registry = MagicMock()
    mock_registry.sync_status_from_cache = AsyncMock()
    mock_registry.get_tool.return_value = mock_tool

    with patch("spectra_tools.validation.get_registry", return_value=mock_registry):
        with patch("spectra_tools.validation.HAS_JSONSCHEMA", True):
            if jsonschema is not None:
                with patch("jsonschema.validate", side_effect=jsonschema.ValidationError("missing target")):
                    tool, error = await validate_and_resolve_tool(mission, "nmap", "1.2.3.4", {})
                assert tool is None
                assert "Invalid arguments" in error.stderr
            else:
                pytest.skip("jsonschema not installed")


@pytest.mark.asyncio
async def test_validate_and_resolve_tool_jsonschema_missing():
    mission = MagicMock()
    mission.log = MagicMock()

    mock_tool = MagicMock()
    mock_tool.is_available = True
    mock_tool.config.execution.args_schema = {"type": "object"}

    mock_registry = MagicMock()
    mock_registry.sync_status_from_cache = AsyncMock()
    mock_registry.get_tool.return_value = mock_tool

    with patch("spectra_tools.validation.get_registry", return_value=mock_registry):
        with patch("spectra_tools.validation.HAS_JSONSCHEMA", False):
            tool, error = await validate_and_resolve_tool(mission, "nmap", "1.2.3.4", {})

    assert tool == mock_tool
    assert error is None
