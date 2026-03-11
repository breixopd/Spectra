"""Sandbox container pool — manages lifecycle of per-mission ephemeral containers."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from docker.errors import APIError, ContainerError, DockerException, ImageNotFound, NotFound
except ImportError:
    DockerException = APIError = ContainerError = ImageNotFound = NotFound = OSError  # type: ignore[assignment,misc]
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models.infrastructure import Sandbox
from app.services.tools.sandbox.models import SandboxInfo

logger = logging.getLogger("spectra.sandbox.pool")


class SandboxPool:
    """Manages per-mission ephemeral Docker containers.

    Each mission gets its own sandbox container running a worker
    that polls a mission-specific PostgreSQL job queue.
    """

    def __init__(self) -> None:
        self.available = False
        self._client: Any = None  # docker.DockerClient
        try:
            import docker
            self._client = docker.from_env()
            self._client.ping()
            self.available = True
            logger.info("SandboxPool initialized — Docker available")
        except (DockerException, OSError) as exc:
            logger.warning("SandboxPool: Docker not available (%s). Sandbox features disabled.", exc)

    @staticmethod
    def get_tier_limits(tier_name: str) -> tuple[str, int]:
        """Parse SANDBOX_RESOURCE_TIERS and return (memory_limit, cpu_shares) for the given tier."""
        settings = get_settings()
        tiers = json.loads(settings.SANDBOX_RESOURCE_TIERS)
        if tier_name not in tiers:
            logger.warning("Unknown resource tier '%s', falling back to 'medium'", tier_name)
            tier_name = "medium"
        tier = tiers[tier_name]
        return tier["memory"], tier["cpu_shares"]

    async def create(self, mission_id: str, *, resource_tier: str = "medium", vpn_config_path: str | None = None, user_id: str | None = None) -> SandboxInfo:
        """Create a new sandbox container for a mission.

        Raises:
            RuntimeError: If Docker is unavailable or max containers reached.
        """
        if not self.available:
            raise RuntimeError("Docker is not available — cannot create sandbox")

        settings = get_settings()

        # Per-user sandbox limit check
        if user_id and settings.SANDBOX_PER_USER_LIMIT > 0:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Sandbox).where(
                        Sandbox.user_id == user_id,
                        Sandbox.status.in_(["creating", "running"]),
                    )
                )
                user_count = len(result.scalars().all())
                if user_count >= settings.SANDBOX_PER_USER_LIMIT:
                    raise RuntimeError(
                        f"Per-user sandbox limit reached ({user_count}/{settings.SANDBOX_PER_USER_LIMIT})"
                    )

        # Check capacity
        running = await self._count_running()
        if running >= settings.SANDBOX_MAX_CONTAINERS:
            raise RuntimeError(
                f"Sandbox limit reached ({running}/{settings.SANDBOX_MAX_CONTAINERS}). "
                "Wait for a mission to finish or increase SANDBOX_MAX_CONTAINERS."
            )

        queue_name = SandboxInfo.make_queue_name(mission_id)
        container_name = f"spectra-sandbox-{mission_id[:8]}"
        sandbox_id = str(uuid.uuid4())

        memory_limit, cpu_shares = self.get_tier_limits(resource_tier)

        # Persist DB row first (status=creating) so orphan cleanup can find it
        async with async_session_maker() as session:
            row = Sandbox(
                id=sandbox_id,
                mission_id=mission_id,
                container_id="",  # filled after container starts
                container_name=container_name,
                queue_name=queue_name,
                status="creating",
                image=settings.SANDBOX_IMAGE,
                resource_tier=resource_tier,
                user_id=user_id,
            )
            session.add(row)
            await session.commit()

        # Build container config — never pass primary DB credentials or signing keys
        environment = {
            "QUEUE_NAME": queue_name,
            "IS_TOOLS_CONTAINER": "true",
            "CONNECT_BACK_HOST": "spectra-app",
            "PLUGIN_SAFE_MODE": str(settings.PLUGIN_SAFE_MODE).lower(),
        }

        # Build volume mounts
        # Use Docker mount objects for both named volumes and bind mounts
        import docker.types

        mounts = [
            # Shared data volume (named Docker volume)
            docker.types.Mount(target="/app/data", source="spectra_data", type="volume"),
            # Tools data volume (named Docker volume — shared tool binaries)
            docker.types.Mount(target="/opt/spectra_tools", source="spectra_tools_data", type="volume"),
        ]

        # Mount plugins from host if bind-mounted, otherwise use app working dir
        import pathlib
        app_root = pathlib.Path(__file__).resolve().parents[4]
        plugins_dir = app_root / "plugins"
        if plugins_dir.is_dir():
            mounts.append(
                docker.types.Mount(target="/app/plugins", source=str(plugins_dir), type="bind", read_only=True)
            )

        # Mount VPN config if provided
        if vpn_config_path:
            mounts.append(
                docker.types.Mount(target="/app/vpn_configs/mission.conf", source=vpn_config_path, type="bind", read_only=True)
            )

        # Create isolated network if enabled
        sandbox_network_id: str | None = None
        container_network = settings.SANDBOX_NETWORK

        if settings.SANDBOX_NETWORK_ISOLATION:
            net_name = f"spectra-sandbox-{mission_id[:8]}"
            net_labels = {"spectra.sandbox": "true", "spectra.mission_id": mission_id}
            try:
                net = await asyncio.to_thread(
                    self._client.networks.create,
                    net_name,
                    driver="bridge",
                    labels=net_labels,
                )
                sandbox_network_id = net.id
                container_network = net_name
                logger.info("Created isolated network %s for mission %s", net_name, mission_id[:8])
            except (APIError, DockerException) as exc:
                logger.error("Failed to create isolated network for mission %s: %s", mission_id[:8], exc)
                raise RuntimeError(f"Sandbox network creation failed: {exc}") from exc

        try:
            container = self._client.containers.run(
                image=settings.SANDBOX_IMAGE,
                name=container_name,
                detach=True,
                network=container_network,
                environment=environment,
                mounts=mounts,
                mem_limit=memory_limit,
                cpu_shares=cpu_shares,
                labels={
                    "spectra.sandbox": "true",
                    "spectra.mission_id": mission_id,
                    "spectra.queue_name": queue_name,
                },
                # Security hardening
                cap_add=["NET_ADMIN", "NET_RAW"],
                cap_drop=["ALL"],
                pids_limit=256,
                read_only=False,  # Tools need to write to /tmp, /opt, etc.
                tmpfs={"/tmp": "size=2G"},
                devices=["/dev/net/tun"],
                restart_policy={"Name": "no"},
            )

            # Connect to shared network for DB access if using isolated network
            if settings.SANDBOX_NETWORK_ISOLATION and sandbox_network_id:
                try:
                    shared_net = self._client.networks.get(settings.SANDBOX_NETWORK)
                    await asyncio.to_thread(shared_net.connect, container)
                    logger.debug("Connected sandbox %s to shared network %s", container_name, settings.SANDBOX_NETWORK)
                except (APIError, NotFound) as exc:
                    logger.warning("Failed to connect sandbox to shared network: %s", exc)

            # Update DB with actual container ID and network ID
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(container_id=container.id, status="running", network_id=sandbox_network_id)
                )
                await session.commit()

            info = SandboxInfo(
                container_id=container.id,
                container_name=container_name,
                mission_id=mission_id,
                queue_name=queue_name,
                status="running",
                image=settings.SANDBOX_IMAGE,
                resource_tier=resource_tier,
                network_id=sandbox_network_id,
            )
            logger.info(
                "Sandbox created: %s (queue=%s, mission=%s, isolated=%s)",
                container_name, queue_name, mission_id[:8], bool(sandbox_network_id),
            )
            return info

        except (APIError, ContainerError, ImageNotFound) as exc:
            # Cleanup isolated network on failure
            if sandbox_network_id:
                try:
                    net = self._client.networks.get(sandbox_network_id)
                    await asyncio.to_thread(net.remove)
                    logger.debug("Cleaned up network %s after creation failure", sandbox_network_id)
                except (APIError, NotFound):
                    logger.debug("Failed to clean up network %s after creation failure", sandbox_network_id)
            # Mark DB row as error
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(status="error", error=str(exc)[:500])
                )
                await session.commit()
            logger.error("Failed to create sandbox for mission %s: %s", mission_id[:8], exc)
            raise RuntimeError(f"Sandbox creation failed: {exc}") from exc

    async def destroy(self, mission_id: str) -> None:
        """Stop and remove the sandbox container for a mission."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Sandbox).where(
                    Sandbox.mission_id == mission_id,
                    Sandbox.status.in_(["creating", "running"]),
                )
            )
            row = result.scalar_one_or_none()

        if not row:
            logger.debug("No active sandbox found for mission %s", mission_id[:8])
            return

        await self._stop_container(row.container_id, row.container_name)

        # Remove isolated network if present
        if row.network_id:
            await self._remove_network(row.network_id, row.container_name)

        async with async_session_maker() as session:
            await session.execute(
                update(Sandbox)
                .where(Sandbox.id == row.id)
                .values(status="destroyed", destroyed_at=datetime.now(UTC))
            )
            await session.commit()

        logger.info("Sandbox destroyed: %s (mission=%s)", row.container_name, mission_id[:8])

    async def get(self, mission_id: str) -> SandboxInfo | None:
        """Get sandbox info for a mission, or None if no active sandbox."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Sandbox).where(
                    Sandbox.mission_id == mission_id,
                    Sandbox.status == "running",
                )
            )
            row = result.scalar_one_or_none()

        if not row:
            return None

        return SandboxInfo(
            container_id=row.container_id,
            container_name=row.container_name,
            mission_id=row.mission_id,
            queue_name=row.queue_name,
            status=row.status,
            image=row.image,
            network_id=row.network_id,
            created_at=row.created_at,
        )

    async def cleanup_all(self) -> int:
        """Remove all sandbox containers. Called on startup/shutdown for orphan recovery."""
        count = 0

        if self.available:
            try:
                containers = self._client.containers.list(
                    all=True, filters={"label": "spectra.sandbox=true"}
                )
                for c in containers:
                    try:
                        c.stop(timeout=5)
                    except Exception:
                        logger.debug("Failed to stop container %s during cleanup", getattr(c, 'name', 'unknown'))
                    try:
                        c.remove(force=True)
                    except Exception:
                        logger.debug("Failed to remove container %s during cleanup", getattr(c, 'name', 'unknown'))
                    count += 1

                # Clean up orphaned sandbox networks
                networks = self._client.networks.list(filters={"label": "spectra.sandbox=true"})
                for net in networks:
                    try:
                        net.remove()
                    except Exception:
                        logger.debug("Failed to remove orphaned network %s", getattr(net, 'name', 'unknown'))
                if networks:
                    logger.info("Cleaned up %d orphaned sandbox networks", len(networks))
            except (APIError, DockerException) as exc:
                logger.warning("Docker cleanup error: %s", exc)

        # Mark all non-destroyed rows as destroyed in DB
        async with async_session_maker() as session:
            await session.execute(
                update(Sandbox)
                .where(Sandbox.status.in_(["creating", "running", "stopping"]))
                .values(status="destroyed", destroyed_at=datetime.now(UTC))
            )
            await session.commit()

        if count:
            logger.info("Cleaned up %d orphaned sandbox containers", count)
        return count

    async def health_check(self) -> dict[str, Any]:
        """Check health of all running sandboxes. Reap expired ones."""
        settings = get_settings()
        result: dict[str, Any] = {"available": self.available, "sandboxes": {}}

        if not self.available:
            return result

        async with async_session_maker() as session:
            rows = await session.execute(
                select(Sandbox).where(Sandbox.status == "running")
            )
            running = list(rows.scalars().all())

        now = datetime.now(UTC)
        for row in running:
            age_seconds = (now - row.created_at).total_seconds()
            alive = self._is_container_alive(row.container_id)

            if not alive or age_seconds > settings.SANDBOX_MAX_LIFETIME:
                reason = "expired" if alive else "dead"
                logger.warning(
                    "Reaping sandbox %s (mission=%s, reason=%s)",
                    row.container_name, row.mission_id[:8], reason,
                )
                await self.destroy(row.mission_id)
                result["sandboxes"][row.mission_id] = reason
            else:
                result["sandboxes"][row.mission_id] = "healthy"

        return result

    # -- Private helpers --

    async def _count_running(self) -> int:
        """Count sandboxes in running or creating state."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Sandbox).where(Sandbox.status.in_(["creating", "running"]))
            )
            return len(list(result.scalars().all()))

    def _is_container_alive(self, container_id: str) -> bool:
        """Check if a Docker container is still running."""
        if not self.available or not container_id:
            return False
        try:
            c = self._client.containers.get(container_id)
            return c.status == "running"
        except Exception:
            # Expected when container was already removed (race with cleanup)
            return False

    async def _stop_container(self, container_id: str, name: str) -> None:
        """Stop and remove a Docker container."""
        if not self.available or not container_id:
            return

        def _do_stop() -> None:
            try:
                c = self._client.containers.get(container_id)
                c.stop(timeout=10)
            except Exception:
                logger.debug("Failed to stop container %s (may already be stopped)", name, exc_info=True)
            try:
                c = self._client.containers.get(container_id)
                c.remove(force=True)
            except Exception:
                logger.debug("Failed to remove container %s (may already be removed)", name, exc_info=True)

        await asyncio.to_thread(_do_stop)

    async def _remove_network(self, network_id: str, sandbox_name: str) -> None:
        """Disconnect all containers and remove an isolated Docker network."""
        if not self.available or not network_id:
            return

        def _do_remove() -> None:
            try:
                net = self._client.networks.get(network_id)
                # Disconnect any remaining containers
                net.reload()
                for cid in list(net.attrs.get("Containers", {}).keys()):
                    try:
                        net.disconnect(cid, force=True)
                    except Exception:
                        logger.debug("Failed to disconnect container %s from network %s", cid[:12], network_id[:12], exc_info=True)
                net.remove()
                logger.info("Removed isolated network %s (sandbox=%s)", network_id[:12], sandbox_name)
            except Exception as exc:
                logger.debug("Network %s already removed or not found: %s", network_id[:12], exc)

        await asyncio.to_thread(_do_remove)
