import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from app.services.tools.installer import ToolInstaller


@pytest.fixture
def mock_registry():
    registry = AsyncMock()
    registry._tools = {}

    # Mock tool
    tool = MagicMock()
    tool.config.id = "nmap"
    tool.config.execution.command = "nmap"
    tool.config.installation.verification_command = None
    tool.config.installation.verification_regex = (
        None  # Explicitly None to avoid MagicMock truthness
    )
    tool.status = "installed"
    tool.error_message = None

    # get_tool is synchronous
    registry.get_tool = MagicMock(return_value=tool)
    registry.install_tool.return_value = True

    return registry


@pytest.fixture
def installer():
    return ToolInstaller()


@pytest.mark.asyncio
@patch("app.services.tools.installer.get_registry")
@patch("app.services.tools.installer.ToolInstaller._is_installed")
async def test_install_success(
    mock_is_installed, mock_get_registry, installer, mock_registry
):
    mock_get_registry.return_value = mock_registry
    mock_is_installed.return_value = False

    result = await installer.install("nmap")

    assert result["success"] is True, f"Failed with error: {result.get('error')}"
    assert result["status"] == "installed"
    mock_registry.install_tool.assert_called_once_with("nmap")


@pytest.mark.asyncio
@patch("app.services.tools.installer.get_registry")
@patch("app.services.tools.installer.ToolInstaller._is_installed")
async def test_install_already_installed(
    mock_is_installed, mock_get_registry, installer, mock_registry
):
    mock_get_registry.return_value = mock_registry
    mock_is_installed.return_value = True

    result = await installer.install("nmap")

    assert result["success"] is True, f"Failed with error: {result.get('error')}"
    mock_registry.install_tool.assert_called_once_with("nmap")


@pytest.mark.asyncio
@patch("app.services.tools.installer.get_registry")
async def test_uninstall_success(mock_get_registry, installer, mock_registry):
    mock_get_registry.return_value = mock_registry
    mock_registry.uninstall_tool.return_value = True

    result = await installer.uninstall("nmap")

    assert result["success"] is True
    assert result["status"] == "uninstalled"


@pytest.mark.asyncio
async def test_is_installed_shutil_check(installer):
    tool = MagicMock()
    tool.config.execution.command = "ls"  # assumes ls is in path
    tool.config.installation.verification_command = None

    # We should mock shutil.which instead of relying on system
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/bin/ls"
        assert await installer._is_installed(tool) is True


@pytest.mark.asyncio
async def test_is_installed_verification_command(installer):
    tool = MagicMock()
    tool.config.execution.command = "custom_tool"
    tool.config.installation.verification_command = "echo verify"
    tool.config.installation.verification_regex = None

    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/bin/custom_tool"

        with patch("asyncio.create_subprocess_shell") as mock_exec:
            process = AsyncMock()
            process.communicate.return_value = (b"verify", b"")
            process.returncode = 0
            mock_exec.return_value = process

            assert await installer._is_installed(tool) is True


@pytest.mark.asyncio
async def test_is_installed_verification_failure(installer):
    tool = MagicMock()
    tool.config.execution.command = "custom_tool"
    tool.config.installation.verification_command = "echo fail"
    tool.config.installation.verification_regex = None

    with patch("shutil.which") as mock_which:
        mock_which.return_value = None  # Binary not found standard way

        with patch("asyncio.create_subprocess_shell") as mock_exec:
            process = AsyncMock()
            process.communicate.return_value = (b"", b"error")
            process.returncode = 1
            mock_exec.return_value = process

            assert await installer._is_installed(tool) is False
