"""Tests for golden image builder."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestGoldenImageBuilder:
    """GoldenImageBuilder class tests."""

    def test_import(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        assert GoldenImageBuilder is not None

    def test_unavailable_without_docker(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        with patch("app.services.tools.sandbox.golden_image.docker", create=True) as mock_docker:
            mock_docker.from_env.side_effect = Exception("No Docker")
            builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
            builder._client = None
            builder._building = False
            builder._lock = MagicMock()
            assert builder.available is False

    def test_parse_plugins_returns_list(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        # Create a fake plugin
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

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        plugins = builder.parse_plugins(str(tmp_path))
        assert len(plugins) == 1
        assert plugins[0]["id"] == "nmap"
        assert plugins[0]["install_method"] == "apt"

    def test_parse_plugins_skips_malformed(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        (tmp_path / "bad.json").write_text("not valid json{{{")

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        plugins = builder.parse_plugins(str(tmp_path))
        assert len(plugins) == 0

    def test_generate_dockerfile_contains_base_image(self, tmp_path):
        from app.core.constants import SANDBOX_BASE_IMAGE as BASE_IMAGE
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugins = [
            {
                "id": "nmap",
                "name": "Nmap",
                "install_method": "apt",
                "install_commands": ["apt-get install -y nmap"],
                "verification_command": "nmap --version",
            },
        ]
        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        dockerfile = builder.generate_dockerfile(plugins)
        assert f"FROM {BASE_IMAGE}" in dockerfile
        assert "nmap" in dockerfile

    def test_generate_dockerfile_handles_pip_tools(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugins = [
            {
                "id": "sqlmap",
                "name": "SQLMap",
                "install_method": "pip",
                "install_commands": ["pip install sqlmap"],
                "verification_command": "sqlmap --version",
            },
        ]
        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        dockerfile = builder.generate_dockerfile(plugins)
        assert "pip install" in dockerfile
        assert "sqlmap" in dockerfile

    def test_generate_dockerfile_handles_go_tools(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugins = [
            {
                "id": "ffuf",
                "name": "ffuf",
                "install_method": "go",
                "install_commands": ["go install github.com/ffuf/ffuf/v2@latest"],
                "verification_command": "",
            },
        ]
        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        dockerfile = builder.generate_dockerfile(plugins)
        assert "go install" in dockerfile

    @pytest.mark.asyncio
    async def test_build_returns_error_when_unavailable(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        result = await builder.build()
        assert result["status"] == "error"
        assert "not available" in result.get("message", "").lower()


class TestGoldenImageValidation:
    """Tests for validate_image method."""

    @pytest.mark.asyncio
    async def test_validate_image_unavailable(self):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = None
        builder._building = False
        builder._lock = MagicMock()
        success, failures = await builder.validate_image("fake:tag")
        assert success is False
        assert "Docker not available" in failures[0]

    @pytest.mark.asyncio
    async def test_validate_image_all_pass(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugin = {
            "id": "nmap",
            "name": "Nmap",
            "installation": {"verification_command": "nmap --version"},
            "execution": {"command": "nmap"},
        }
        (tmp_path / "nmap.json").write_text(json.dumps(plugin))

        mock_container = MagicMock()
        mock_container.exec_run.return_value = (0, b"Nmap 7.94")
        mock_container.stop.return_value = None
        mock_container.remove.return_value = None

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = mock_client
        builder._building = False
        builder._lock = MagicMock()

        success, failures = await builder.validate_image("test:tag", str(tmp_path))
        assert success is True
        assert failures == []

    @pytest.mark.asyncio
    async def test_validate_image_tool_fails(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugin = {
            "id": "nmap",
            "name": "Nmap",
            "installation": {"verification_command": "nmap --version"},
            "execution": {"command": "nmap"},
        }
        (tmp_path / "nmap.json").write_text(json.dumps(plugin))

        mock_container = MagicMock()
        mock_container.exec_run.return_value = (127, b"not found")
        mock_container.stop.return_value = None
        mock_container.remove.return_value = None

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = mock_client
        builder._building = False
        builder._lock = MagicMock()

        success, failures = await builder.validate_image("test:tag", str(tmp_path))
        assert success is False
        assert len(failures) == 1
        assert "Nmap" in failures[0]

    @pytest.mark.asyncio
    async def test_validate_image_fallback_to_version_flag(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        # Plugin with no verification_command — should fall back to --version/--help
        plugin = {
            "id": "gobuster",
            "name": "Gobuster",
            "installation": {},
            "execution": {"command": "gobuster"},
        }
        (tmp_path / "gobuster.json").write_text(json.dumps(plugin))

        mock_container = MagicMock()
        mock_container.exec_run.return_value = (0, b"v3.6")
        mock_container.stop.return_value = None
        mock_container.remove.return_value = None

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = mock_client
        builder._building = False
        builder._lock = MagicMock()

        success, failures = await builder.validate_image("test:tag", str(tmp_path))
        assert success is True
        assert failures == []

    @pytest.mark.asyncio
    async def test_validate_image_skips_parameterised_commands(self, tmp_path):
        from app.services.tools.sandbox.golden_image import GoldenImageBuilder

        plugin = {
            "id": "impacket",
            "name": "Impacket",
            "installation": {},
            "execution": {"command": "impacket-{sub_tool}"},
        }
        (tmp_path / "impacket.json").write_text(json.dumps(plugin))

        mock_container = MagicMock()
        mock_container.stop.return_value = None
        mock_container.remove.return_value = None

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        builder = GoldenImageBuilder.__new__(GoldenImageBuilder)
        builder._client = mock_client
        builder._building = False
        builder._lock = MagicMock()

        success, failures = await builder.validate_image("test:tag", str(tmp_path))
        assert success is True
        assert failures == []
    """Singleton accessors."""

    def test_get_set_image_builder(self):
        from app.services.tools.sandbox import get_image_builder, set_image_builder

        mock = MagicMock()
        set_image_builder(mock)  # type: ignore[arg-type]
        assert get_image_builder() is mock
        set_image_builder(None)
