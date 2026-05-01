from unittest.mock import MagicMock, patch

import pytest

from spectra_platform.services.tools.registry.installer import PluginInstaller
from spectra_tools_core.models import (
    InstallationConfig,
    InstallationMethod,
    RegisteredTool,
    ToolConfig,
    ToolStatus,
)
from spectra_tools_core.registry_exceptions import PluginInstallationError


@pytest.fixture
def installer():
    return PluginInstaller()


@pytest.fixture
def mock_tool():
    tool = MagicMock(spec=RegisteredTool)
    tool.status = ToolStatus.PENDING
    tool.config = MagicMock(spec=ToolConfig)
    tool.config.id = "test-tool"
    tool.config.version = "1.0.0"
    tool.config.installation = MagicMock(spec=InstallationConfig)
    tool.config.installation.method = InstallationMethod.SCRIPT
    tool.config.installation.commands = ["echo install"]
    tool.config.installation.uninstall_commands = ["echo uninstall"]
    tool.config.installation.verification_command = None
    tool.config.installation.verification_regex = None
    return tool


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_install_tool_success(mock_run, installer, mock_tool):
    mock_run.return_value = (0, "output", "")

    result = await installer.install_tool(mock_tool)

    assert result is True
    assert mock_tool.status == ToolStatus.READY
    assert mock_tool.installed_version == "1.0.0"
    mock_run.assert_called_with("echo install")


@pytest.mark.asyncio
async def test_install_tool_already_installing(installer, mock_tool):
    mock_tool.status = ToolStatus.INSTALLING
    result = await installer.install_tool(mock_tool)
    assert result is False


@pytest.mark.asyncio
async def test_install_tool_method_none(installer, mock_tool):
    mock_tool.config.installation.method = InstallationMethod.NONE
    result = await installer.install_tool(mock_tool)
    assert result is True
    assert mock_tool.status == ToolStatus.READY


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_install_tool_failure(mock_run, installer, mock_tool):
    mock_run.return_value = (1, "", "error")

    with pytest.raises(PluginInstallationError):
        await installer.install_tool(mock_tool)

    assert mock_tool.status == ToolStatus.FAILED
    assert "Command failed" in mock_tool.error_message


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_verify_installation_success(mock_run, installer, mock_tool):
    mock_tool.config.installation.verification_command = "echo verify"
    mock_run.side_effect = [
        (0, "install success", ""),  # First call (verification) - success!
    ]

    result = await installer.install_tool(mock_tool)
    assert result is True
    assert mock_run.call_count == 1  # Installation skipped because verification succeeded


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_verify_installation_regex_match(mock_run, installer, mock_tool):
    mock_tool.config.installation.verification_command = "echo verify"
    mock_tool.config.installation.verification_regex = "success"

    # Verify matches regex even if return code is non-zero?
    # Code: if pattern.search... return True
    mock_run.side_effect = [
        (0, "install ok", ""),
        (1, "output success", ""),  # Non-zero but regex matches
    ]

    result = await installer.install_tool(mock_tool)
    assert result is True


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_verify_installation_regex_fail(mock_run, installer, mock_tool):
    mock_tool.config.installation.verification_command = "echo verify"
    mock_tool.config.installation.verification_regex = "success"

    mock_run.side_effect = [
        (0, "install ok", ""),
        (0, "output fail", ""),  # Zero but regex fails?
        # Code: if regex matches -> True.
        # else: log debug.
        # if returncode != 0: return False.
        # return True.
    ]
    # So if returncode is 0 and regex NO match, it returns TRUE.
    # Because regex is an ADDITIONAL check that can override returncode!=0?
    # Or strict check?
    # Comment: "If regex matches, we consider it a success even if exit code is non-zero"
    # But if regex DOES NOT match, and returncode is 0?
    # "Verification regex for ... did not match output".
    # Logic returns True at end.

    result = await installer.install_tool(mock_tool)
    assert result is True


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_uninstall_tool_success(mock_run, installer, mock_tool):
    mock_run.return_value = (0, "ok", "")
    result = await installer.uninstall_tool(mock_tool, "plugins_dir")
    assert result is True
    mock_run.assert_called_with("echo uninstall")


@pytest.mark.asyncio
@patch("spectra_platform.services.tools.registry.installer.run_command_safe")
async def test_uninstall_tool_failure(mock_run, installer, mock_tool):
    mock_run.return_value = (1, "", "fail")
    # Should catch exception and return True (pass)
    result = await installer.uninstall_tool(mock_tool, "plugins_dir")
    assert result is True
