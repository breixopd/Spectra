"""Tests for the server provisioner — env-var sanitisation and connection building."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_scaling.provisioning.provisioner import ServerConfig, ServerProvisioner


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


@pytest.mark.asyncio
class TestBuildConnKwargs:
    async def test_with_password(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1", password="secret")
        with patch.object(provisioner, "_ensure_known_host", new_callable=AsyncMock, return_value="/tmp/known_hosts"):
            result = await provisioner._build_conn_kwargs(config)
        assert result is not None
        assert result["host"] == "10.0.0.1"
        assert result["password"] == "secret"
        assert result["port"] == 22
        assert result["username"] == "root"

    async def test_with_private_key(self, provisioner: ServerProvisioner):
        # asyncssh.import_private_key requires a real key — mock it
        with (
            patch.object(provisioner, "_ensure_known_host", new_callable=AsyncMock, return_value="/tmp/known_hosts"),
            patch("spectra_scaling.provisioning.provisioner.asyncssh.import_private_key") as mock_import,
        ):
            mock_import.return_value = "fake-key-obj"
            config = ServerConfig(host="10.0.0.1", private_key="-----BEGIN RSA...")
            result = await provisioner._build_conn_kwargs(config)

        assert result is not None
        assert result["client_keys"] == ["fake-key-obj"]
        assert "password" not in result

    async def test_no_auth(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1")
        result = await provisioner._build_conn_kwargs(config)
        assert result is None

    async def test_known_hosts_uses_tofu_file(self, provisioner: ServerProvisioner):
        config = ServerConfig(host="10.0.0.1", password="pw")
        with patch.object(
            provisioner, "_ensure_known_host", new_callable=AsyncMock, return_value="/tmp/provisioner_known_hosts"
        ):
            result = await provisioner._build_conn_kwargs(config)
        assert result is not None
        assert result["known_hosts"] == "/tmp/provisioner_known_hosts"


# ---------------------------------------------------------------------------
# _ensure_known_host
# ---------------------------------------------------------------------------


def _mock_subprocess_proc(stdout: str = "", returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), b""))
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
class TestEnsureKnownHost:
    async def test_existing_entry_skips_keyscan(self, provisioner: ServerProvisioner, tmp_path):
        known_hosts_path = tmp_path / "config" / "provisioner_known_hosts"
        known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        known_hosts_path.write_text("[example.com]:2222 ssh-ed25519 AAAAC3existing\n", encoding="utf-8")

        with (
            patch.object(provisioner, "_known_hosts_path", return_value=known_hosts_path),
            patch("asyncio.create_subprocess_exec") as mock_exec,
        ):
            result = await provisioner._ensure_known_host(ServerConfig(host="example.com", port=2222, password="pw"))

        assert result == known_hosts_path
        mock_exec.assert_not_called()

    async def test_pinned_entry_replaces_existing_host_and_skips_keyscan(
        self, provisioner: ServerProvisioner, tmp_path
    ):
        known_hosts_path = tmp_path / "config" / "provisioner_known_hosts"
        known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        known_hosts_path.write_text(
            "[example.com]:2222 ssh-ed25519 AAAACold\nother.example ssh-ed25519 AAAAOTHER\n",
            encoding="utf-8",
        )
        pinned_entry = "[example.com]:2222 ssh-ed25519 AAAAPINNED"

        with (
            patch.object(provisioner, "_known_hosts_path", return_value=known_hosts_path),
            patch("asyncio.create_subprocess_exec") as mock_exec,
        ):
            result = await provisioner._ensure_known_host(
                ServerConfig(host="example.com", port=2222, password="pw", ssh_known_host=pinned_entry)
            )

        assert result == known_hosts_path
        assert known_hosts_path.read_text(encoding="utf-8") == (
            "other.example ssh-ed25519 AAAAOTHER\n[example.com]:2222 ssh-ed25519 AAAAPINNED\n"
        )
        mock_exec.assert_not_called()

    async def test_keyscan_appends_new_host_and_logs(self, provisioner: ServerProvisioner, tmp_path, caplog):
        known_hosts_path = tmp_path / "config" / "provisioner_known_hosts"
        proc = _mock_subprocess_proc(stdout="[example.com]:2222 ssh-ed25519 AAAAC3new\n")

        with (
            patch.object(provisioner, "_known_hosts_path", return_value=known_hosts_path),
            patch.object(provisioner, "_ssh_keyscan_executable", return_value="/usr/bin/ssh-keyscan"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc) as mock_exec,
            caplog.at_level("INFO"),
        ):
            result = await provisioner._ensure_known_host(ServerConfig(host="example.com", port=2222, password="pw"))

        assert result == known_hosts_path
        assert known_hosts_path.read_text(encoding="utf-8") == "[example.com]:2222 ssh-ed25519 AAAAC3new\n"
        mock_exec.assert_called_once_with(
            "/usr/bin/ssh-keyscan",
            "-p",
            "2222",
            "example.com",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert "Trusted new SSH host key on first use" in caplog.text

    async def test_keyscan_failure_raises_runtime_error(self, provisioner: ServerProvisioner, tmp_path):
        known_hosts_path = tmp_path / "config" / "provisioner_known_hosts"
        proc = _mock_subprocess_proc(returncode=1)

        with (
            patch.object(provisioner, "_known_hosts_path", return_value=known_hosts_path),
            patch.object(provisioner, "_ssh_keyscan_executable", return_value="/usr/bin/ssh-keyscan"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
        ):
            with pytest.raises(RuntimeError, match=r"ssh-keyscan failed for bad\.example:22"):
                await provisioner._ensure_known_host(ServerConfig(host="bad.example", password="pw"))


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

        with (
            patch.object(provisioner, "_ensure_known_host", new_callable=AsyncMock, return_value="/tmp/known_hosts"),
            patch("spectra_scaling.provisioning.provisioner.asyncssh.connect", return_value=mock_conn),
        ):
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
        with (
            patch.object(provisioner, "_ensure_known_host", new_callable=AsyncMock, return_value="/tmp/known_hosts"),
            patch(
                "spectra_scaling.provisioning.provisioner.asyncssh.connect",
                side_effect=OSError("Connection refused"),
            ),
        ):
            config = ServerConfig(host="10.0.0.1", password="pw")
            result = await provisioner.verify_connection(config)

        assert result["connected"] is False
        assert "Connection refused" in result["error"]

    async def test_verify_returns_clear_error_when_keyscan_fails(self, provisioner: ServerProvisioner):
        with patch.object(
            provisioner, "_ensure_known_host", new_callable=AsyncMock, side_effect=RuntimeError("ssh-keyscan failed")
        ):
            config = ServerConfig(host="10.0.0.1", password="pw")
            result = await provisioner.verify_connection(config)

        assert result == {"connected": False, "error": "ssh-keyscan failed"}
