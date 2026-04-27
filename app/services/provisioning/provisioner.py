"""SSH-based remote server provisioner."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import asyncssh as _asyncssh
except ModuleNotFoundError:
    _asyncssh = None

from app.core.config import settings
from app.infrastructure.paths import data_path
from app.services.provisioning.recipes import CONTAINER_NAMES, PROVISIONING_RECIPES

logger = logging.getLogger(__name__)

_VALID_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)

_MISSING_ASYNCSSH_MESSAGE = (
    "Missing optional dependency 'asyncssh'; install it to use remote provisioning operations"
)


class _AsyncSSHShim:
    """Patchable fallback when asyncssh is unavailable."""

    class DisconnectError(Exception):
        """Fallback disconnect error type used by tests and exception handlers."""

    @staticmethod
    def connect(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(_MISSING_ASYNCSSH_MESSAGE)

    @staticmethod
    def import_private_key(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(_MISSING_ASYNCSSH_MESSAGE)


asyncssh = _asyncssh if _asyncssh is not None else _AsyncSSHShim()
ASYNCSSH_AVAILABLE = _asyncssh is not None


@dataclass
class ServerConfig:
    """Connection details for a remote server."""

    host: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    private_key: str | None = None
    ssh_known_host: str | None = None
    service_type: str = ""  # sandbox_worker
    service_port: int = 8080
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class ProvisioningResult:
    """Result of a provisioning operation."""

    success: bool
    server_host: str
    service_type: str
    service_url: str = ""
    logs: list[str] = field(default_factory=list)
    error: str = ""
    health_check_passed: bool = False


class ServerProvisioner:
    """Auto-provisions remote servers over SSH for Spectra services."""

    @staticmethod
    def _require_asyncssh() -> None:
        if not ASYNCSSH_AVAILABLE:
            raise RuntimeError(_MISSING_ASYNCSSH_MESSAGE)

    async def provision(self, config: ServerConfig) -> ProvisioningResult:
        """Provision a remote server with the specified service.

        1. SSH connect
        2. Run recipe steps (install Docker, pull images, start service)
        3. Health check
        4. Return result with service URL
        """
        logger.info("Starting provisioning: host=%s service=%s", config.host, config.service_type)
        result = ProvisioningResult(
            success=False,
            server_host=config.host,
            service_type=config.service_type,
        )

        recipe = PROVISIONING_RECIPES.get(config.service_type)
        if not recipe:
            result.error = f"Unknown service type: {config.service_type}"
            result.logs.append(f"ERROR: {result.error}")
            return result

        try:
            conn_kwargs = await self._build_conn_kwargs(config)
        except (OSError, RuntimeError, ValueError) as e:
            result.error = str(e)
            result.logs.append(f"ERROR: {result.error}")
            logger.error("Failed to prepare SSH trust for %s:%s: %s", config.host, config.port, e)
            return result
        if conn_kwargs is None:
            result.error = "No authentication method provided (password or private key required)"
            result.logs.append(f"ERROR: {result.error}")
            return result

        try:
            self._require_asyncssh()
            result.logs.append(f"Connecting to {config.host}:{config.port} as {config.username}...")
            async with asyncssh.connect(**conn_kwargs) as conn:
                result.logs.append("Connected successfully")

                env_vars = self._build_env_vars(config)

                registry = getattr(settings, "DOCKER_REGISTRY", None) or "ghcr.io/spectra"
                from app._meta.version import __version__ as app_version

                version = app_version or "latest"

                # Filter reserved keys from extra_env to prevent format conflicts
                _reserved = {"service_port", "env_vars", "spectra_host", "registry", "version"}
                safe_extra = {k: v for k, v in config.extra_env.items() if k not in _reserved}

                for step in recipe:
                    result.logs.append(f"\n--- Step: {step.name} ---")
                    command = step.command.format(
                        service_port=config.service_port,
                        env_vars=self._format_env_vars(env_vars),
                        spectra_host=settings.CONNECT_BACK_HOST,
                        registry=registry,
                        version=version,
                        **safe_extra,
                    )

                    try:
                        ssh_result = await asyncio.wait_for(
                            conn.run(command, check=False),
                            timeout=step.timeout,
                        )

                        if ssh_result.stdout:
                            for line in str(ssh_result.stdout).strip().split("\n")[-20:]:
                                result.logs.append(f"  {line}")

                        if ssh_result.returncode != 0:  # type: ignore[operator]
                            if step.required:
                                err_msg = (
                                    ssh_result.stderr.strip()
                                    if ssh_result.stderr
                                    else f"Exit code {ssh_result.returncode}"
                                )
                                result.error = f"Step '{step.name}' failed: {err_msg}"
                                result.logs.append(f"FAILED: {result.error}")
                                return result
                            else:
                                result.logs.append("  (non-critical step failed, continuing)")
                        else:
                            result.logs.append("  OK")

                    except TimeoutError:
                        if step.required:
                            result.error = f"Step '{step.name}' timed out after {step.timeout}s"
                            result.logs.append(f"TIMEOUT: {result.error}")
                            return result
                        result.logs.append("  (step timed out, continuing)")

                # Health check
                service_url = f"http://{config.host}:{config.service_port}"
                result.logs.append(f"\n--- Health Check: {service_url}/health ---")

                try:
                    health_result = await asyncio.wait_for(
                        conn.run(f"curl -sf {service_url}/health || echo 'HEALTH_FAIL'", check=False),
                        timeout=30,
                    )
                    if health_result.stdout and "HEALTH_FAIL" not in health_result.stdout:  # type: ignore[operator]
                        result.health_check_passed = True
                        result.logs.append("  Health check PASSED")
                    else:
                        result.logs.append("  Health check FAILED (service may still be starting)")
                except TimeoutError:
                    result.logs.append("  Health check timed out")

                result.success = True
                result.service_url = service_url
                result.logs.append(f"\nProvisioning complete: {service_url}")
                logger.info("Provisioning succeeded: host=%s url=%s", config.host, service_url)

        except asyncssh.DisconnectError as e:
            result.error = f"SSH connection failed: {e}"
            result.logs.append(f"ERROR: {result.error}")
            logger.error("SSH disconnect during provisioning: host=%s error=%s", config.host, e)
        except OSError as e:
            result.error = f"Cannot reach server: {e}"
            result.logs.append(f"ERROR: {result.error}")
            logger.error("Cannot reach server: host=%s error=%s", config.host, e)
        except (RuntimeError, ValueError) as e:
            result.error = f"Unexpected error: {e}"
            result.logs.append(f"ERROR: {result.error}")
            logger.exception("Provisioning failed for %s", config.host)

        return result

    async def verify_connection(self, config: ServerConfig) -> dict[str, Any]:
        """Test SSH connectivity without provisioning."""
        try:
            conn_kwargs = await self._build_conn_kwargs(config)
        except (OSError, RuntimeError, ValueError) as e:
            return {"connected": False, "error": str(e)}
        if conn_kwargs is None:
            return {"connected": False, "error": "No auth method"}

        try:
            self._require_asyncssh()
            async with asyncssh.connect(**conn_kwargs) as conn:  # type: ignore[arg-type]
                result = await conn.run(
                    "uname -a && docker --version 2>/dev/null || echo 'docker_not_installed'",
                    check=False,
                )
                has_docker = "docker_not_installed" not in (result.stdout or "")  # type: ignore[operator]
                return {
                    "connected": True,
                    "system_info": (result.stdout or "").strip().split("\n")[0],  # type: ignore[union-attr]
                    "docker_installed": has_docker,
                }
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            return {"connected": False, "error": str(e)}

    async def deprovision(self, config: ServerConfig) -> ProvisioningResult:
        """Remove Spectra service from a remote server."""
        logger.info("Starting deprovision: host=%s service=%s", config.host, config.service_type)
        result = ProvisioningResult(
            success=False,
            server_host=config.host,
            service_type=config.service_type,
        )

        try:
            conn_kwargs = await self._build_conn_kwargs(config)
        except (OSError, RuntimeError, ValueError) as e:
            result.error = str(e)
            result.logs.append(f"ERROR: {result.error}")
            return result
        if conn_kwargs is None:
            result.error = "No auth method"
            result.logs.append(f"ERROR: {result.error}")
            return result

        try:
            self._require_asyncssh()
            async with asyncssh.connect(**conn_kwargs) as conn:  # type: ignore[arg-type]
                result.logs.append("Connected, stopping Spectra services...")
                container = CONTAINER_NAMES.get(config.service_type, "spectra-sandbox-worker")
                stop_cmd = (
                    f"docker stop {container} 2>/dev/null; "
                    f"docker rm {container} 2>/dev/null; "
                    "docker network rm spectra-remote 2>/dev/null; "
                    "echo 'cleanup_done'"
                )
                await conn.run(stop_cmd, check=False)
                result.logs.append("Services stopped and removed")
                result.success = True
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            result.error = str(e)
            result.logs.append(f"ERROR: {result.error}")

        return result

    async def _build_conn_kwargs(self, config: ServerConfig) -> dict[str, Any] | None:
        """Build asyncssh connection kwargs. Returns None if no auth available."""
        if not config.private_key and not config.password:
            return None

        known_hosts_path = await self._ensure_known_host(config)
        conn_kwargs: dict[str, Any] = {
            "host": config.host,
            "port": config.port,
            "username": config.username,
            "known_hosts": str(known_hosts_path),
        }
        if config.private_key:
            conn_kwargs["client_keys"] = [asyncssh.import_private_key(config.private_key)]
        elif config.password:
            conn_kwargs["password"] = config.password
        return conn_kwargs

    def _known_hosts_path(self) -> Path:
        """Return the local known_hosts file used for TOFU SSH trust."""
        return data_path("config", "provisioner_known_hosts")

    @staticmethod
    def _known_hosts_target(hostname: str, port: int) -> str:
        return hostname if port == 22 else f"[{hostname}]:{port}"

    @staticmethod
    def _line_matches_known_host(line: str, expected_host: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False
        host_field = stripped.split()[0]
        host_tokens = {token.strip() for token in host_field.split(",")}
        return expected_host in host_tokens

    @staticmethod
    def _normalize_known_host_lines(entry: str) -> list[str]:
        lines: list[str] = []
        for raw_line in entry.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped not in lines:
                lines.append(stripped)
        return lines

    @staticmethod
    def _validate_scan_target(hostname: str, port: int) -> str:
        candidate = hostname.strip()
        if candidate != hostname or not candidate:
            raise ValueError("SSH hostname must be a non-empty host or IP address")
        if not 1 <= port <= 65535:
            raise ValueError(f"SSH port must be between 1 and 65535, got {port}")
        if candidate.startswith("-"):
            raise ValueError(f"Invalid SSH hostname: {hostname!r}")

        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            if not _VALID_HOSTNAME_RE.fullmatch(candidate):
                raise ValueError(f"Invalid SSH hostname: {hostname!r}") from None

        return candidate

    @staticmethod
    def _ssh_keyscan_executable() -> str:
        executable = shutil.which("ssh-keyscan")
        if executable is None:
            raise RuntimeError("ssh-keyscan executable not found in PATH")
        return executable

    async def _ensure_known_host(self, config: ServerConfig) -> Path:
        """Ensure the remote host has a persisted known_hosts entry before connecting."""
        known_hosts_path = self._known_hosts_path()
        await asyncio.to_thread(known_hosts_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(known_hosts_path.touch, exist_ok=True)
        await asyncio.to_thread(known_hosts_path.chmod, 0o600)

        existing_text = await asyncio.to_thread(known_hosts_path.read_text, encoding="utf-8")
        existing_lines = existing_text.splitlines()
        expected_host = self._known_hosts_target(config.host, config.port)

        if config.ssh_known_host is not None:
            pinned_lines = self._normalize_known_host_lines(config.ssh_known_host)
            if not pinned_lines:
                raise ValueError(f"Pinned known-host entry for {config.host}:{config.port} is empty")

            retained_lines = [
                line for line in existing_lines if not self._line_matches_known_host(line, expected_host)
            ]
            merged_lines = list(dict.fromkeys([*retained_lines, *pinned_lines]))
            await asyncio.to_thread(
                known_hosts_path.write_text,
                "\n".join(merged_lines) + "\n",
                encoding="utf-8",
            )
            logger.info("Persisted pinned SSH host key for %s:%s", config.host, config.port)
            return known_hosts_path

        for line in existing_lines:
            if self._line_matches_known_host(line, expected_host):
                return known_hosts_path

        scan_host = self._validate_scan_target(config.host, config.port)
        ssh_keyscan = self._ssh_keyscan_executable()

        try:
            # The host and port are validated, and the executable path is fully resolved.
            proc = await asyncio.create_subprocess_exec(
                ssh_keyscan,
                "-p",
                str(config.port),
                scan_host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                detail = (stderr_data.decode("utf-8", errors="replace").strip() or "no error output")
                raise RuntimeError(
                    f"ssh-keyscan failed for {config.host}:{config.port}: {detail}"
                )
        except TimeoutError as exc:
            raise RuntimeError(
                f"ssh-keyscan timed out for {config.host}:{config.port}"
            ) from exc
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            detail = str(exc).strip() or "no error output"
            raise RuntimeError(
                f"ssh-keyscan failed for {config.host}:{config.port}: {detail}"
            ) from exc

        scanned_lines = self._normalize_known_host_lines(stdout_data.decode("utf-8", errors="replace"))
        if not scanned_lines:
            raise RuntimeError(f"ssh-keyscan returned no host keys for {config.host}:{config.port}")

        def _append_lines() -> None:
            with known_hosts_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(scanned_lines))
                handle.write("\n")

        await asyncio.to_thread(_append_lines)

        logger.info(
            "Trusted new SSH host key on first use for %s:%s using %s",
            config.host,
            config.port,
            known_hosts_path,
        )
        return known_hosts_path

    def _build_env_vars(self, config: ServerConfig) -> dict[str, str]:
        """Build environment variables for the remote service."""
        env: dict[str, str] = {
            "SPECTRA_HOST": settings.CONNECT_BACK_HOST,
            "SPECTRA_PORT": "5000",
        }

        env.update(config.extra_env)
        return env

    @staticmethod
    def _format_env_vars(env: dict[str, str]) -> str:
        """Format environment variables for docker command, safely quoted."""
        parts = []
        for key, value in env.items():
            if not key.replace("_", "").isalnum():
                logger.warning("Skipping invalid env var key: %s", key)
                continue
            parts.append(f"-e {shlex.quote(f'{key}={value}')}")
        return " ".join(parts)
