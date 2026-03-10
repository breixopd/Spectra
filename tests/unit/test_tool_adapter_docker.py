import pytest
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
        parsing={"format": "xml", "mapping": {"open_ports": "portid"}},
    )


@pytest.fixture
def request_obj():
    return ToolExecutionRequest(tool_id="nmap-docker", target="example.com", args={})


def test_build_command_no_docker(docker_config, request_obj):
    """Test command building runs locally without docker exec wrapping."""
    adapter = CommandToolAdapter(docker_config)

    cmd = adapter.build_command(request_obj, output_dir="/tmp/out")

    # No docker exec wrapping — sandboxes handle isolation externally
    assert "docker exec" not in cmd
    assert "timeout -k 5s" in cmd
    assert "nmap" in cmd


def test_build_command_local_execution(docker_config, request_obj):
    """Test command building produces local execution command."""
    adapter = CommandToolAdapter(docker_config)
    cmd = adapter.build_command(request_obj, output_dir="/tmp/out")

    # Should not be docker-wrapped
    assert "docker exec" not in cmd

    # Check timeout wrapper
    assert "timeout -k 5s" in cmd
    assert "nmap" in cmd


def test_build_command_output_dir(docker_config, request_obj):
    """Test that output dir is included in command."""
    adapter = CommandToolAdapter(docker_config)
    cmd = adapter.build_command(request_obj, output_dir="/tmp/out")

    assert "/tmp/out/nmap-docker_output" in cmd


def test_build_command_no_permissions_injection(docker_config, request_obj):
    """Test no chmod injection in command."""
    adapter = CommandToolAdapter(docker_config)
    cmd = adapter.build_command(request_obj, output_dir="/tmp/out")

    assert "chmod 666" not in cmd
    assert "/tmp/out/nmap-docker_output" in cmd
