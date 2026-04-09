"""Tests for the server provisioner — env-var sanitisation and connection building."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

asyncssh = pytest.importorskip("asyncssh", reason="asyncssh not installed")
from app.services.provisioning.provisioner import ServerConfig, ServerProvisioner


@pytest.fixture
def provisioner():
    return ServerProvisioner()


# ---------------------------------------------------------------------------
# _format_env_vars
# ---------------------------------------------------------------------------


class TestFormatEnvVars:
    def test_valid_keys(self, provisioner: ServerProvisioner):
        result = provisioner._format_env_vars({"MY_VAR": "hello", "PORT": "8080"})
        assert "-e" in result
        assert "MY_VAR=hello" in result
        assert "PORT=8080" in result

    def test_rejects_invalid_keys(self, provisioner: ServerProvisioner):
        result = provisioner._format_env_vars({"GOOD_KEY": "ok", "BAD;KEY": "nope"})
        assert "GOOD_KEY=ok" in result
        assert "BAD;KEY" not in result

    def test_rejects_key_with_spaces(self, provisioner: ServerProvisioner):
        result = provisioner._format_env_vars({"HAS SPACE": "val"})
        assert result == ""

    def test_rejects_key_with_backtick(self, provisioner: ServerProvisioner):
        result = provisioner._format_env_vars({"`cmd`": "val"})
        assert result == ""

    def test_shell_metacharacters_in_value(self, provisioner: ServerProvisioner):
        # Values with shell metacharacters must be safely quoted
        result = provisioner._format_env_vars({"KEY": "val; rm -rf /"})
        assert "KEY=" in result
        # shlex.quote wraps the whole KEY=VALUE, so injection chars are escaped
        assert "rm -rf" in result  # value is retained but safely quoted
        # Verify no unquoted semicolons outside of quoting
        parts = result.split("-e ")
        for part in parts:
            part = part.strip()
            if part:
                # shlex.quote produces 'KEY=val; rm -rf /' which is safe
                assert part.startswith(("'", '"')) or ";" not in part

    def test_empty_dict(self, provisioner: ServerProvisioner):
        assert provisioner._format_env_vars({}) == ""

    def test_dollar_sign_in_value(self, provisioner: ServerProvisioner):
        result = provisioner._format_env_vars({"KEY": "$HOME"})
        assert "KEY=$HOME" in result


# ---------------------------------------------------------------------------
# _build_conn_kwargs
# ---------------------------------------------------------------------------


class TestBuildConnKwargs:
    def test_with_password(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1", password="secret")
        result = provisioner._build_conn_kwargs(config)
        assert result is not None
        assert result["host"] == "10.0.0.1"
        assert result["password"] == "secret"
        assert result["port"] == 22
        assert result["username"] == "root"

    def test_with_private_key(self, provisioner: ServerProvisioner):
        # asyncssh.import_private_key requires a real key — mock it
        with patch("app.services.provisioning.provisioner.asyncssh.import_private_key") as mock_import:
            mock_import.return_value = "fake-key-obj"
            config = ServerConfig(host="10.0.0.1", private_key="-----BEGIN RSA...")
            result = provisioner._build_conn_kwargs(config)

        assert result is not None
        assert result["client_keys"] == ["fake-key-obj"]
        assert "password" not in result

    def test_no_auth(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1")
        result = provisioner._build_conn_kwargs(config)
        assert result is None

    def test_known_hosts_none(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1", password="pw")
        result = provisioner._build_conn_kwargs(config)
        assert result is not None
        assert result["known_hosts"] is None


# ---------------------------------------------------------------------------
# verify_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifyConnection:
    async def test_verify_success(self, provisioner: ServerProvisioner):
        mock_run_result = MagicMock()
        mock_run_result.stdout = "Linux test 5.15\ndocker version 24.0.0"

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_run_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.provisioning.provisioner.asyncssh.connect", return_value=mock_conn):
            config = ServerConfig(host="10.0.0.1", password="pw")
            result = await provisioner.verify_connection(config)

        assert result["connected"] is True
        assert result["docker_installed"] is True

    async def test_verify_no_auth(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1")
        result = await provisioner.verify_connection(config)
        assert result["connected"] is False
        assert "No auth" in result["error"]

    async def test_verify_connection_error(self, provisioner: ServerProvisioner):
        with patch(
            "app.services.provisioning.provisioner.asyncssh.connect",
            side_effect=OSError("Connection refused"),
        ):
            config = ServerConfig(host="10.0.0.1", password="pw")
            result = await provisioner.verify_connection(config)

        assert result["connected"] is False
        assert "Connection refused" in result["error"]
