import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.tools.sandbox.golden_image import GoldenImageBuilder


def test_builder_not_available():
    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        assert builder.available is False


def test_parse_plugins_empty_dir(tmp_path):
    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        result = builder.parse_plugins(str(tmp_path))
        assert result == []


def test_parse_plugins_valid(tmp_path):
    plugin = {
        "id": "nmap",
        "name": "Nmap",
        "installation": {
            "method": "apt",
            "commands": ["apt-get install -y nmap"],
            "verification_command": "nmap --version",
        },
    }
    (tmp_path / "nmap.json").write_text(json.dumps(plugin))

    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        result = builder.parse_plugins(str(tmp_path))

    assert len(result) == 1
    assert result[0]["id"] == "nmap"
    assert result[0]["install_method"] == "apt"


def test_parse_plugins_malformed(tmp_path):
    (tmp_path / "bad.json").write_text("not json")
    (tmp_path / "good.json").write_text(json.dumps({"id": "x", "installation": {"method": "apt", "commands": []}}))

    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        result = builder.parse_plugins(str(tmp_path))

    assert len(result) == 1


def test_generate_dockerfile_empty():
    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        df = builder.generate_dockerfile([])
    assert "FROM" in df
    assert "apt-get" in df


def test_generate_dockerfile_with_plugins():
    plugins = [
        {"id": "nmap", "install_method": "apt", "install_commands": ["apt-get install -y nmap netcat"]},
        {"id": "sqlmap", "install_method": "pip", "install_commands": ["pip install sqlmap"]},
        {"id": "custom", "install_method": "script", "install_commands": ["echo hello"]},
        {"id": "g tool", "install_method": "go", "install_commands": ["go install example.com/tool@latest"]},
    ]

    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        df = builder.generate_dockerfile(plugins)

    assert "nmap" in df
    assert "netcat" in df
    assert "sqlmap" in df
    assert "echo hello" in df
    assert "go install" in df


@pytest.mark.asyncio
async def test_validate_image_no_docker():
    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        success, failures = await builder.validate_image("test:latest")
    assert success is False
    assert "Docker not available" in failures[0]


@pytest.mark.asyncio
async def test_build_no_docker():
    with patch("docker.from_env", side_effect=ImportError("no docker")):
        builder = GoldenImageBuilder()
        result = await builder.build()
    assert result["status"] == "error"
    assert "Docker not available" in result["message"]
