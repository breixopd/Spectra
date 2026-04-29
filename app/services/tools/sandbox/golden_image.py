"""Golden image builder — automatically builds the spectra-tools Docker image from plugin definitions."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import shlex
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spectra_common.constants import SANDBOX_BASE_IMAGE

logger = logging.getLogger(__name__)


class GoldenImageBuilder:
    """Builds the spectra-tools Docker image from plugin JSON definitions.

    Parses plugins/*.json to extract installation commands, generates an
    ephemeral Dockerfile, and builds the image via Docker API. Uses a
    temporary tag during build for atomic swap on success.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._building = False
        self._lock = asyncio.Lock()
        try:
            import docker

            self._client = docker.from_env()
            self._client.ping()
        except (OSError, RuntimeError, ImportError) as exc:
            logger.warning("GoldenImageBuilder: Docker not available (%s)", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def building(self) -> bool:
        return self._building

    def parse_plugins(self, plugins_dir: str = "plugins") -> list[dict[str, Any]]:
        """Parse all plugin JSON files and extract installation info.

        Returns a list of dicts with keys: id, name, install_method, install_commands, verification_command
        """
        plugins_path = Path(plugins_dir)
        if not plugins_path.is_dir():
            logger.warning("Plugins directory not found: %s", plugins_dir)
            return []

        plugins = []
        for json_file in sorted(plugins_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                installation = data.get("installation", {})
                if not installation:
                    continue

                plugins.append(
                    {
                        "id": data.get("id", json_file.stem),
                        "name": data.get("name", json_file.stem),
                        "version": data.get("version", ""),
                        "install_method": installation.get("method", ""),
                        "install_commands": installation.get("commands", []),
                        "verification_command": installation.get("verification_command", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed plugin %s: %s", json_file.name, exc)

        return plugins

    def _plugin_manifest(self, plugins: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """Return deterministic plugin provenance manifest and SHA-256 digest."""
        manifest = [
            {
                "id": plugin.get("id", ""),
                "name": plugin.get("name", ""),
                "version": plugin.get("version", ""),
                "install_method": plugin.get("install_method", ""),
                "verification_command": plugin.get("verification_command", ""),
                "install_commands_sha256": hashlib.sha256(
                    json.dumps(plugin.get("install_commands", []), sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            for plugin in sorted(plugins, key=lambda item: str(item.get("id", "")))
        ]
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
        return manifest, digest

    def generate_dockerfile(self, plugins: list[dict[str, Any]]) -> str:
        """Generate a Dockerfile that installs all plugin tools.

        The generated Dockerfile layers:
        1. Base Kali image with core system packages
        2. Python virtualenv + pip dependencies
        3. Tool installation from plugin definitions
        4. Go tools setup
        5. Worker entrypoint
        """
        # Group install commands by method
        apt_packages: list[str] = []
        pip_packages: list[str] = []
        custom_commands: list[str] = []
        go_packages: list[str] = []

        def _extract_install_args(cmd: str, executables: set[str]) -> list[str]:
            """Extract package names from shell install commands without fallback branches."""
            try:
                parts = shlex.split(cmd)
            except ValueError:
                return []

            for index, part in enumerate(parts[:-1]):
                if part not in executables or parts[index + 1] != "install":
                    continue

                packages: list[str] = []
                for token in parts[index + 2 :]:
                    if token in {"&&", "||", ";", "|"} or token.startswith("("):
                        break
                    if token.startswith("-"):
                        continue
                    packages.append(token)
                return packages

            return []

        for plugin in plugins:
            method = plugin["install_method"]
            commands = plugin["install_commands"]

            if method == "apt":
                # Extract package names from apt commands
                for cmd in commands:
                    for package in _extract_install_args(cmd, {"apt", "apt-get"}):
                        if package not in apt_packages:
                            apt_packages.append(package)
            elif method == "pip":
                for cmd in commands:
                    for package in _extract_install_args(cmd, {"pip", "pip3"}):
                        if package not in pip_packages:
                            pip_packages.append(package)
            elif method == "go":
                for cmd in commands:
                    if "go install" in cmd:
                        go_packages.append(cmd)
            elif method == "script":
                custom_commands.extend(commands)

        manifest, manifest_sha = self._plugin_manifest(plugins)
        tool_ids = ",".join(item["id"] for item in manifest)

        lines = [
            f"FROM {SANDBOX_BASE_IMAGE}",
            "",
            'LABEL org.opencontainers.image.title="Spectra Tools (Golden)"',
            'LABEL org.opencontainers.image.description="Auto-built security tools image"',
            f'LABEL io.spectra.golden-image.manifest-sha256="{manifest_sha}"',
            f'LABEL io.spectra.golden-image.plugins="{tool_ids}"',
            "",
            "WORKDIR /app",
            "",
            "# System packages + tool packages",
            "RUN apt-get update && \\",
            "    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\",
            "    python3 python3-pip python3-venv python3-dev \\",
            "    gcc libpq-dev libffi-dev pkg-config libpcap-dev \\",
            "    curl wget git jq unzip \\",
            "    iputils-ping iproute2 netcat-openbsd iptables \\",
            "    wireguard-tools openvpn \\",
            "    golang \\",
            "    seclists \\",
        ]

        if apt_packages:
            lines.append(f"    {' '.join(sorted(set(apt_packages)))} \\")

        lines.extend(
            [
                "    && apt-get clean \\",
                "    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*",
                "",
                "# Go setup",
                "ENV GOPATH=/root/go",
                "ENV PATH=$PATH:/root/go/bin:/usr/local/go/bin",
                "",
                "# Python virtualenv",
                "RUN python3 -m venv /opt/venv",
                'ENV PATH="/opt/venv/bin:/opt/spectra_tools:$PATH"',
                "",
                "# Python dependencies",
                "COPY requirements/worker.txt .",
                "RUN pip install --no-cache-dir --upgrade pip && \\",
                "    pip install --no-cache-dir -r worker.txt",
                "",
            ]
        )

        if pip_packages:
            lines.append(f"RUN pip install --no-cache-dir {' '.join(sorted(set(pip_packages)))}")
            lines.append("")

        if go_packages:
            lines.append("# Go tools")
            for cmd in go_packages:
                lines.append(f"RUN {cmd}")
            lines.append("")

        if custom_commands:
            lines.append("# Custom tool installations")
            for cmd in custom_commands:
                lines.append(f"RUN {cmd}")
            lines.append("")

        lines.extend(
            [
                "# Worker code",
                "COPY packages/tools-core/src/spectra_tools_core/ ./spectra_tools_core/",
                "COPY app/ ./app/",
                "COPY plugins/ ./plugins/",
                "",
                "# Entrypoint",
                'CMD ["python", "-m", "spectra_worker"]',
            ]
        )

        return "\n".join(lines)

    async def _store_build_status(self, result: dict[str, Any]) -> None:
        """Persist latest golden-image build metadata for audit/compliance views."""
        try:
            from sqlalchemy import select as _select

            from app.core.database import async_session_maker as _asm
            from app.models.infrastructure import SystemStatus

            async with _asm() as session:
                existing = await session.execute(_select(SystemStatus).where(SystemStatus.key == "golden_image_build"))
                row = existing.scalar_one_or_none()
                if row:
                    row.value = result
                else:
                    session.add(SystemStatus(key="golden_image_build", value=result))
                await session.commit()
        except (OSError, RuntimeError) as exc:
            logger.warning("Failed to store build status: %s", exc)

    async def validate_image(
        self, image_tag: str, plugins_dir: str = "plugins"
    ) -> tuple[bool, list[str]]:
        """Validate all tools are functional in a newly built image.

        Starts a temporary container, runs each plugin's verification command
        (falling back to ``<cmd> --version`` / ``<cmd> --help``), and returns
        ``(success, list_of_failure_descriptions)``.
        """
        if not self.available:
            return False, ["Docker not available"]

        failures: list[str] = []
        plugins_path = Path(plugins_dir)
        container = None

        try:
            container = await asyncio.to_thread(
                self._client.containers.run,
                image_tag,
                command="sleep 60",
                detach=True,
                remove=False,
            )

            for json_file in sorted(plugins_path.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

                verification_cmd = (
                    data.get("installation", {}).get("verification_command", "")
                )
                exec_cmd = data.get("execution", {}).get("command", "")
                plugin_name = data.get("name", json_file.stem)

                if verification_cmd:
                    exit_code, _ = await asyncio.to_thread(
                        container.exec_run,
                        ["/bin/sh", "-c", verification_cmd],
                    )
                    if exit_code == 0:
                        continue
                    # Verification command failed — record and try next plugin
                    failures.append(f"{plugin_name}: verification failed ({verification_cmd})")
                    continue

                if not exec_cmd:
                    continue

                # Derive base binary (handle templates like "impacket-{sub_tool}")
                base_bin = exec_cmd.split()[0]
                if "{" in base_bin:
                    continue  # Cannot verify parameterised commands

                # Fallback: try --version then --help
                verified = False
                for flag in ("--version", "--help"):
                    safe_cmd = f"{shlex.quote(base_bin)} {flag}"
                    exit_code, _ = await asyncio.to_thread(
                        container.exec_run,
                        ["/bin/sh", "-c", safe_cmd],
                    )
                    if exit_code == 0:
                        verified = True
                        break
                if not verified:
                    failures.append(f"{plugin_name}: {base_bin} not functional")

        except (OSError, RuntimeError) as exc:
            failures.append(f"Validation error: {exc}")
        finally:
            if container is not None:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(container.stop, timeout=5)
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(container.remove, force=True)

        return (len(failures) == 0, failures)

    async def build(self, plugins_dir: str = "plugins", target_tag: str = "spectra-tools:latest") -> dict[str, Any]:
        """Build the golden image from plugin definitions.

        Uses a temporary tag for the build. On success, re-tags as target_tag.
        On failure, the old image remains untouched.

        Returns a dict with build status and details.
        """
        if not self.available:
            return {"status": "error", "message": "Docker not available"}

        async with self._lock:
            if self._building:
                return {"status": "skipped", "message": "Build already in progress"}
            self._building = True

        temp_tag = f"spectra-tools:build-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        result: dict[str, Any] = {"status": "building", "tag": temp_tag, "started_at": datetime.now(UTC).isoformat()}

        try:
            plugins = self.parse_plugins(plugins_dir)
            if not plugins:
                return {"status": "error", "message": "No plugins found"}

            manifest, manifest_sha = self._plugin_manifest(plugins)
            dockerfile_content = self.generate_dockerfile(plugins)
            result["plugins_count"] = len(plugins)
            result["plugin_manifest_sha256"] = manifest_sha
            result["plugin_manifest"] = manifest
            result["dockerfile_lines"] = len(dockerfile_content.splitlines())
            result["provenance"] = {
                "builder": "spectra-golden-image",
                "source": str(Path(plugins_dir).resolve()),
                "target_tag": target_tag,
                "base_image": SANDBOX_BASE_IMAGE,
            }

            logger.info("Building golden image %s from %d plugins...", temp_tag, len(plugins))

            # Write Dockerfile to temp dir and build
            # The build context needs to include requirements/worker.txt, app/, and plugins/
            project_root = Path(plugins_dir).resolve().parent

            def _do_build() -> tuple[Any, list[str]]:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".Dockerfile", dir=str(project_root), delete=False
                ) as f:
                    f.write(dockerfile_content)
                    dockerfile_path = f.name

                try:
                    image, build_logs = self._client.images.build(
                        path=str(project_root),
                        dockerfile=dockerfile_path,
                        tag=temp_tag,
                        rm=True,
                        forcerm=True,
                    )
                    log_lines = []
                    for chunk in build_logs:
                        if "stream" in chunk:
                            log_lines.append(chunk["stream"].strip())
                    return image, log_lines
                finally:
                    Path(dockerfile_path).unlink(missing_ok=True)

            image, build_logs = await asyncio.to_thread(_do_build)

            # Validate all tools in the new image before promoting
            valid, validation_failures = await self.validate_image(temp_tag, plugins_dir)
            result["validation_failures"] = validation_failures

            if not valid:
                logger.error(
                    "Golden image validation failed for %s: %s",
                    temp_tag,
                    validation_failures,
                )
                result["status"] = "validation_failed"
                result["message"] = (
                    f"{len(validation_failures)} tool(s) failed validation"
                )
                result["completed_at"] = datetime.now(UTC).isoformat()

                # Clean up the failed temp image
                try:
                    await asyncio.to_thread(
                        self._client.images.remove, temp_tag, force=True,
                    )
                except OSError:
                    logger.warning("Failed to clean up temp image %s", temp_tag)

                await self._store_build_status(result)
                return result

            # Atomic swap: tag as target
            tag_repo = target_tag.split(":")[0]
            tag_ver = target_tag.split(":")[-1] if ":" in target_tag else "latest"
            await asyncio.to_thread(image.tag, tag_repo, tag_ver)

            result["status"] = "success"
            result["image_id"] = image.id
            result["completed_at"] = datetime.now(UTC).isoformat()
            result["build_log_lines"] = len(build_logs)

            logger.info("Golden image built successfully: %s (%d plugins)", target_tag, len(plugins))

            # Scan the image if scanning is enabled
            from app.core.config import get_settings as _get_settings

            _build_settings = _get_settings()
            from app.services.tools.sandbox.image_scanner import ImageScanner

            scanner = ImageScanner()
            if scanner.available:
                scan_result = await scanner.scan(
                    target_tag,
                    block_critical=_build_settings.SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL,
                )
                result["scan"] = scan_result.to_dict()
                if scan_result.blocked:
                    # Untag the image to prevent it from being used
                    try:
                        await asyncio.to_thread(self._client.images.remove, target_tag, noprune=True)
                        result["status"] = "blocked"
                        result["message"] = f"Image blocked: {scan_result.critical} critical CVEs"
                        logger.warning("Golden image blocked due to %d critical CVEs", scan_result.critical)
                    except OSError as untag_exc:
                        logger.error("Failed to untag blocked image: %s", untag_exc)

            await self._store_build_status(result)
            return result

        except (OSError, RuntimeError) as exc:
            result["status"] = "error"
            result["error"] = str(exc)[:500]
            result["completed_at"] = datetime.now(UTC).isoformat()
            logger.error("Golden image build failed: %s", exc)

            # Try to clean up temp image
            try:
                await asyncio.to_thread(self._client.images.remove, temp_tag, force=True)
            except OSError:
                logger.warning("Failed to clean up temp image %s", temp_tag)

            await self._store_build_status(result)
            return result
        finally:
            self._building = False

    async def get_build_status(self) -> dict[str, Any] | None:
        """Get the last build status from SystemStatus."""
        try:
            from sqlalchemy import select as _select

            from app.core.database import async_session_maker as _asm
            from app.models.infrastructure import SystemStatus

            async with _asm() as session:
                result = await session.execute(_select(SystemStatus).where(SystemStatus.key == "golden_image_build"))
                row = result.scalar_one_or_none()
                if row and isinstance(row.value, dict):
                    return row.value
                return None
        except (OSError, RuntimeError):
            return None
