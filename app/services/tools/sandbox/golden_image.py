"""Golden image builder — automatically builds the spectra-tools Docker image from plugin definitions."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.constants import SANDBOX_BASE_IMAGE

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
                        "install_method": installation.get("method", ""),
                        "install_commands": installation.get("commands", []),
                        "verification_command": installation.get("verification_command", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed plugin %s: %s", json_file.name, exc)

        return plugins

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

        for plugin in plugins:
            method = plugin["install_method"]
            commands = plugin["install_commands"]

            if method == "apt":
                # Extract package names from apt commands
                for cmd in commands:
                    if "apt-get install" in cmd:
                        # Parse: "apt-get install -y pkg1 pkg2"
                        parts = cmd.split("install")[-1].strip().split()
                        for p in parts:
                            if not p.startswith("-") and p not in apt_packages:
                                apt_packages.append(p)
            elif method == "pip":
                for cmd in commands:
                    if "pip install" in cmd or "pip3 install" in cmd:
                        parts = cmd.split("install")[-1].strip().split()
                        for p in parts:
                            if not p.startswith("-") and p not in pip_packages:
                                pip_packages.append(p)
            elif method == "go":
                for cmd in commands:
                    if "go install" in cmd:
                        go_packages.append(cmd)
            elif method == "script":
                custom_commands.extend(commands)

        lines = [
            f"FROM {SANDBOX_BASE_IMAGE}",
            "",
            'LABEL org.opencontainers.image.title="Spectra Tools (Golden)"',
            'LABEL org.opencontainers.image.description="Auto-built security tools image"',
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
                "COPY app/ ./app/",
                "COPY plugins/ ./plugins/",
                "",
                "# Entrypoint",
                'CMD ["python", "-m", "app.worker"]',
            ]
        )

        return "\n".join(lines)

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

            dockerfile_content = self.generate_dockerfile(plugins)
            result["plugins_count"] = len(plugins)
            result["dockerfile_lines"] = len(dockerfile_content.splitlines())

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

            # Atomic swap: tag as target
            tag_repo = target_tag.split(":")[0]
            tag_ver = target_tag.split(":")[-1] if ":" in target_tag else "latest"
            await asyncio.to_thread(image.tag, tag_repo, tag_ver)

            result["status"] = "success"
            result["image_id"] = image.id
            result["completed_at"] = datetime.now(UTC).isoformat()
            result["build_log_lines"] = len(build_logs)

            logger.info("Golden image built successfully: %s (%d plugins)", target_tag, len(plugins))

            # Store build status in system status
            try:
                from sqlalchemy import select as _select

                from app.core.database import async_session_maker as _asm
                from app.models.infrastructure import SystemStatus

                async with _asm() as session:
                    existing = await session.execute(
                        _select(SystemStatus).where(SystemStatus.key == "golden_image_build")
                    )
                    row = existing.scalar_one_or_none()
                    if row:
                        row.value = result
                    else:
                        session.add(SystemStatus(key="golden_image_build", value=result))
                    await session.commit()
            except (OSError, RuntimeError) as exc:
                logger.debug("Failed to store build status: %s", exc)

            # Scan the image if scanning is enabled
            from app.core.config import get_settings as _get_settings

            _build_settings = _get_settings()
            if _build_settings.SANDBOX_IMAGE_SCAN_ENABLED:
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
                logger.debug("Failed to clean up temp image %s", temp_tag)

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
