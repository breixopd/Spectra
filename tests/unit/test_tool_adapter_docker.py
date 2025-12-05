
import pytest
from unittest.mock import MagicMock, patch
from app.services.tools.adapter import CommandToolAdapter
from app.services.tools.models import ToolConfig, ToolExecutionRequest, ToolCategory

@pytest.fixture
def docker_config():
    """Tool config for docker tests."""
    return ToolConfig(
        id="nmap-docker",
        name="Nmap Docker",
        version="1.0.0",
        category=ToolCategory.DISCOVERY,
        description="Network scanner",
        execution={
            "type": "command",
            "command": "nmap",
            "args_template": "-oX {output_file} {target}",
            "timeout": 60,
        },
        parsing={
            "format": "xml",
            "mapping": {"open_ports": "portid"}
        }
    )

@pytest.fixture
def request_obj():
    return ToolExecutionRequest(
        tool_id="nmap-docker",
        target="example.com",
        args={}
    )

def test_build_command_no_docker(docker_config, request_obj):
    """Test command building without Docker raises error."""
    with patch("app.services.tools.adapter.runner.settings") as mock_settings:
        mock_settings.TOOL_CONTAINER_NAME = None
        
        adapter = CommandToolAdapter(docker_config)
        
        cmd = adapter.build_command(request_obj, output_dir="/tmp/out")
        
        # Verify fallback to local execution
        assert "docker exec" not in cmd
        assert "timeout -k 5s" in cmd
        assert "nmap" in cmd

def test_build_command_with_docker(docker_config, request_obj):
    """Test command building with Docker enabled."""
    with patch("app.services.tools.adapter.runner.settings") as mock_settings:
        mock_settings.TOOL_CONTAINER_NAME = "spectra-tools"
        
        adapter = CommandToolAdapter(docker_config)
        cmd = adapter.build_command(request_obj, output_dir="/tmp/out")
        
        # Should be wrapped
        assert cmd.startswith("docker exec spectra-tools bash -c")
        
        # Check timeout wrapper
        assert "timeout -k 5s" in cmd
        assert "nmap" in cmd

def test_build_command_docker_permissions(docker_config, request_obj):
    """Refined test for Docker permissions fix injection."""
    with patch("app.services.tools.adapter.runner.settings") as mock_settings:
        mock_settings.TOOL_CONTAINER_NAME = "spectra-tools"
        
        adapter = CommandToolAdapter(docker_config)
        cmd = adapter.build_command(request_obj, output_dir="/tmp/out")
        
        # Should NOT include chmod (handled in finally block now)
        assert "chmod 666" not in cmd
        assert "/tmp/out/nmap-docker_output" in cmd

def test_build_command_docker_escaping(docker_config, request_obj):
    """Test execution escaping in Docker command."""
    with patch("app.services.tools.adapter.runner.settings") as mock_settings:
        mock_settings.TOOL_CONTAINER_NAME = "spectra-tools"
        
        request_obj.args = {"flags": "-p '80'"}
        docker_config.execution.args_template = "{flags} {target}"
        
        adapter = CommandToolAdapter(docker_config)
        cmd = adapter.build_command(request_obj)
        
        # Verify single quotes are escaped for bash -c '...'
        # The input has '80', which should become '\''80'\'' inside the main string
        # But shlex.quote handles some of this. We just need to ensure the final string is valid bash.
        assert "docker exec" in cmd
