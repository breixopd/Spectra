"""SSH-based remote server provisioner."""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

import asyncssh

from app.core.config import settings
from app.services.provisioning.recipes import CONTAINER_NAMES, PROVISIONING_RECIPES

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Connection details for a remote server."""

    host: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    private_key: str | None = None
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

        conn_kwargs = self._build_conn_kwargs(config)
        if conn_kwargs is None:
            result.error = "No authentication method provided (password or private key required)"
            result.logs.append(f"ERROR: {result.error}")
            return result

        try:
            result.logs.append(f"Connecting to {config.host}:{config.port} as {config.username}...")
            async with asyncssh.connect(**conn_kwargs) as conn:
                result.logs.append("Connected successfully")

                env_vars = self._build_env_vars(config)

                for step in recipe:
                    result.logs.append(f"\n--- Step: {step.name} ---")
                    command = step.command.format(
                        service_port=config.service_port,
                        env_vars=self._format_env_vars(env_vars),
                        spectra_host=settings.CONNECT_BACK_HOST,
                        **config.extra_env,
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

                    except TimeoutError:  # noqa: PERF203
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
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            result.logs.append(f"ERROR: {result.error}")
            logger.exception("Provisioning failed for %s", config.host)

        return result

    async def verify_connection(self, config: ServerConfig) -> dict[str, Any]:
        """Test SSH connectivity without provisioning."""
        conn_kwargs = self._build_conn_kwargs(config)
        if conn_kwargs is None:
            return {"connected": False, "error": "No auth method"}

        try:
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
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def deprovision(self, config: ServerConfig) -> ProvisioningResult:
        """Remove Spectra service from a remote server."""
        logger.info("Starting deprovision: host=%s service=%s", config.host, config.service_type)
        result = ProvisioningResult(
            success=False,
            server_host=config.host,
            service_type=config.service_type,
        )

        conn_kwargs = self._build_conn_kwargs(config)
        if conn_kwargs is None:
            result.error = "No auth method"
            result.logs.append(f"ERROR: {result.error}")
            return result

        try:
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
        except Exception as e:
            result.error = str(e)
            result.logs.append(f"ERROR: {result.error}")

        return result

    def _build_conn_kwargs(self, config: ServerConfig) -> dict[str, Any] | None:
        """Build asyncssh connection kwargs. Returns None if no auth available."""
        conn_kwargs: dict[str, Any] = {
            "host": config.host,
            "port": config.port,
            "username": config.username,
            # SECURITY: known_hosts=None disables host-key verification, allowing MITM.
            # Acceptable for automated provisioning of ephemeral servers, but should
            # be replaced with a pinned key or trust-on-first-use policy for
            # long-lived infrastructure.
            "known_hosts": None,
        }
        if config.private_key:
            conn_kwargs["client_keys"] = [asyncssh.import_private_key(config.private_key)]
        elif config.password:
            conn_kwargs["password"] = config.password
        else:
            return None
        return conn_kwargs

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
