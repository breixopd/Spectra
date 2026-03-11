"""Tests for golden image builder."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr


class TestGoldenImageConfig:
    """Auto-build image config setting."""

    def test_auto_build_default_true(self):
        from app.core.config import Settings
        s = Settings(DATABASE_URL=SecretStr("sqlite:///test.db"))
        assert s.SANDBOX_AUTO_BUILD_IMAGE is True


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
            }
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
        from app.services.tools.sandbox.golden_image import BASE_IMAGE, GoldenImageBuilder
        plugins = [
            {"id": "nmap", "name": "Nmap", "install_method": "apt",
             "install_commands": ["apt-get install -y nmap"], "verification_command": "nmap --version"},
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
            {"id": "sqlmap", "name": "SQLMap", "install_method": "pip",
             "install_commands": ["pip install sqlmap"], "verification_command": "sqlmap --version"},
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
            {"id": "ffuf", "name": "ffuf", "install_method": "go",
             "install_commands": ["go install github.com/ffuf/ffuf/v2@latest"], "verification_command": ""},
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


class TestImageBuilderSingleton:
    """Singleton accessors."""

    def test_get_set_image_builder(self):
        from app.services.tools.sandbox import get_image_builder, set_image_builder
        mock = MagicMock()
        set_image_builder(mock)  # type: ignore[arg-type]
        assert get_image_builder() is mock
        set_image_builder(None)
