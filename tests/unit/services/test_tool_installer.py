from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_tools.installer import ToolInstaller


@pytest.fixture
def mock_registry():
    with patch("spectra_tools.installer.get_registry") as mock_get_registry:
        registry = MagicMock()
        mock_get_registry.return_value = registry

        # Ensure async methods are AsyncMock
        registry.load_plugins = AsyncMock()
        registry.install_tool = AsyncMock(return_value=True)
        registry.uninstall_tool = AsyncMock(return_value=True)

        # Mock _tools dict
        registry._tools = {}

        yield registry


@pytest.mark.asyncio
async def test_install_success(mock_registry):
    installer = ToolInstaller(check_persistence=False)

    # Mock registry behavior
    mock_tool = MagicMock()
    mock_tool.status = "ready"

    # Since installer checks (tool_id not in registry._tools), we need to ensure it IS there
    # or ensure load_plugins is called.
    mock_registry._tools = {"test-tool": mock_tool}
    mock_registry.get_tool.return_value = mock_tool

    # Mock _is_installed to return False initially
    with patch.object(installer, "_is_installed", new_callable=AsyncMock) as mock_is_installed:
        mock_is_installed.return_value = False

        result = await installer.install("test-tool")

        assert result["success"] is True
        assert result["status"] == "ready"
        mock_registry.install_tool.assert_called_once_with("test-tool")


@pytest.mark.asyncio
async def test_install_already_installed(mock_registry):
    installer = ToolInstaller(check_persistence=True)

    mock_tool = MagicMock()
    mock_registry._tools = {"test-tool": mock_tool}
    mock_registry.get_tool.return_value = mock_tool

    with patch.object(installer, "_is_installed", new_callable=AsyncMock) as mock_is_installed:
        mock_is_installed.return_value = True

        # If already installed, it logs and does 'pass', allowing execution to proceed to install_tool
        await installer.install("test-tool")

        # So install_tool IS called
        assert mock_registry.install_tool.called


@pytest.mark.asyncio
async def test_uninstall_success(mock_registry):
    installer = ToolInstaller()

    result = await installer.uninstall("test-tool")

    assert result["success"] is True
    assert result["status"] == "uninstalled"
    mock_registry.uninstall_tool.assert_called_once_with("test-tool")


@pytest.mark.asyncio
async def test_uninstall_failure(mock_registry):
    installer = ToolInstaller()

    mock_registry.uninstall_tool = AsyncMock(side_effect=RuntimeError("Uninstall failed"))

    result = await installer.uninstall("test-tool")

    assert result["success"] is False
    assert result["status"] == "failed"
    assert "Uninstall failed" in result["error"]
