"""Warm pool — maintains pre-warmed idle sandbox containers for instant mission assignment."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models.infrastructure import Sandbox
from app.services.tools.sandbox.models import SandboxInfo

logger = logging.getLogger(__name__)


def _sandbox_database_url(raw_url: str) -> str:
    """Rewrite compose-only host aliases to names resolvable by ad hoc sandboxes."""
    parsed = urlparse(raw_url)
    if parsed.hostname != "db":
        return raw_url
    netloc = parsed.netloc.replace("@db:", "@spectra-db:").replace("//db:", "//spectra-db:")
    if parsed.netloc.endswith("@db"):
        netloc = netloc[:-3] + "spectra-db"
    return urlunparse(parsed._replace(netloc=netloc))


class WarmPoolManager:
    """Maintains a pool of idle pre-warmed sandbox containers.

    Warm containers sit idle with a placeholder queue name. When a mission
    needs a sandbox, it claims a warm one — the queue is reconfigured and
    the container is reassigned. A replacement warm container is spawned
    in the background.
    """

    WARM_STATUS = "warm"
    WARM_QUEUE_PREFIX = "warm_"

    def __init__(self, pool: Any) -> None:
        """Initialize with a reference to the SandboxPool for container operations."""
        self._pool = pool  # SandboxPool instance
        self._maintain_lock = asyncio.Lock()

    async def claim(
        self, mission_id: str, *, resource_tier: str = "medium", user_id: str | None = None
    ) -> SandboxInfo | None:
        """Claim a warm container for a mission.

        Uses SELECT FOR UPDATE to prevent race conditions between concurrent claims.
        Returns SandboxInfo if a warm container was claimed, None if pool is empty.
        """
        queue_name = SandboxInfo.make_queue_name(mission_id)

        async with async_session_maker() as session:
            # Atomically claim one warm container
            result = await session.execute(
                select(Sandbox).where(Sandbox.status == self.WARM_STATUS).with_for_update(skip_locked=True).limit(1)
            )
            warm = result.scalar_one_or_none()

            if not warm:
                return None

            # Reassign to mission
            warm.mission_id = mission_id
            warm.queue_name = queue_name
            warm.status = "running"
            warm.resource_tier = resource_tier
            warm.user_id = user_id
            await session.commit()

            # Stop warm container — we create a real one with correct queue env.
            # Still faster than cold start because the image is cached.
            await self._pool._stop_container(warm.container_id, warm.container_name)

        # Create the real sandbox with the mission's queue
        try:
            info = await self._pool.create(
                mission_id,
                resource_tier=resource_tier,
                user_id=user_id,
            )
            logger.info("Claimed warm container for mission %s (tier=%s)", mission_id[:8], resource_tier)

            # Spawn replacement in background
            asyncio.create_task(self._spawn_warm_container())

            return info
        except (OSError, RuntimeError) as exc:
            logger.error("Failed to create sandbox after claiming warm container: %s", exc)
            return None

    async def maintain(self) -> None:
        """Ensure the warm pool has the configured number of idle containers.

        Called periodically by a background task.
        """
        settings = get_settings()
        if not self._pool.available:
            return

        async with self._maintain_lock:
            current_warm = await self._count_warm()
            needed = settings.SANDBOX_WARM_POOL_SIZE - current_warm

            if needed <= 0:
                return

            logger.info(
                "Warm pool: %d/%d containers, spawning %d", current_warm, settings.SANDBOX_WARM_POOL_SIZE, needed
            )

            for _ in range(needed):
                await self._spawn_warm_container()

    async def cleanup(self) -> int:
        """Remove all warm containers. Called on shutdown."""
        count = 0
        async with async_session_maker() as session:
            result = await session.execute(select(Sandbox).where(Sandbox.status == self.WARM_STATUS))
            warm_containers = list(result.scalars().all())

        for sb in warm_containers:
            try:
                await self._pool._stop_container(sb.container_id, sb.container_name)
                if sb.network_id:
                    await self._pool._remove_network(sb.network_id, sb.container_name)
                count += 1
            except (OSError, RuntimeError) as exc:
                logger.warning("Failed to cleanup warm container %s: %s", sb.container_name, exc)

        # Mark all warm as destroyed in DB
        async with async_session_maker() as session:
            await session.execute(
                update(Sandbox)
                .where(Sandbox.status == self.WARM_STATUS)
                .values(status="destroyed", destroyed_at=datetime.now(UTC))
            )
            await session.commit()

        if count:
            logger.info("Cleaned up %d warm pool containers", count)
        return count

    async def _spawn_warm_container(self) -> None:
        """Create a single warm container."""
        settings = get_settings()
        try:
            placeholder_id = f"warm-{uuid.uuid4().hex[:8]}"
            queue_name = f"{self.WARM_QUEUE_PREFIX}{placeholder_id}"
            container_name = f"spectra-warm-{placeholder_id[:8]}"
            sandbox_id = str(uuid.uuid4())

            # Persist DB row
            async with async_session_maker() as session:
                row = Sandbox(
                    id=sandbox_id,
                    mission_id=placeholder_id,
                    container_id="",
                    container_name=container_name,
                    queue_name=queue_name,
                    status=self.WARM_STATUS,
                    image=settings.SANDBOX_IMAGE,
                    resource_tier="medium",
                )
                session.add(row)
                await session.commit()

            # Warm workers must share the live DB config so they can consume
            # their assigned PostgreSQL queues when promoted to a mission.
            environment = {
                "QUEUE_NAME": queue_name,
                "IS_TOOLS_CONTAINER": "true",
                "CONNECT_BACK_HOST": "spectra-app",
                "PLUGIN_SAFE_MODE": str(settings.PLUGIN_SAFE_MODE).lower(),
                "DATABASE_URL": _sandbox_database_url(settings.DATABASE_URL.get_secret_value()),
                "DATA_ROOT": settings.DATA_ROOT,
            }

            # Minimal volume mounts for warm containers
            import docker.types

            mounts = [
                docker.types.Mount(
                    target="/app/data",
                    source=self._pool._resolve_volume_name("spectra_data"),
                    type="volume",
                ),
                docker.types.Mount(
                    target="/opt/spectra_tools",
                    source=self._pool._resolve_volume_name("spectra_tools_data"),
                    type="volume",
                ),
            ]

            # Create network if isolation enabled
            network_id = None
            shared_network_name = self._pool._resolve_shared_network_name(settings.SANDBOX_NETWORK)
            container_network = shared_network_name

            if settings.SANDBOX_NETWORK_ISOLATION:
                net_name = f"spectra-warm-{placeholder_id[:8]}"
                try:
                    net = await asyncio.to_thread(
                        self._pool._client.networks.create,
                        net_name,
                        driver="bridge",
                        labels={"spectra.sandbox": "true", "spectra.warm": "true"},
                    )
                    network_id = net.id
                    container_network = net_name
                except OSError:
                    logger.debug("Failed to create isolated network, falling back to shared")

            container = self._pool._client.containers.run(
                image=settings.SANDBOX_IMAGE,
                name=container_name,
                detach=True,
                network=container_network,
                environment=environment,
                mounts=mounts,
                mem_limit="512m",  # Warm containers use minimal resources
                cpu_shares=256,
                labels={
                    "spectra.sandbox": "true",
                    "spectra.warm": "true",
                },
                cap_add=["NET_ADMIN", "NET_RAW"],
                cap_drop=["ALL"],
                pids_limit=256,
                tmpfs={"/tmp": "size=2G"},
                devices=["/dev/net/tun"],
                restart_policy={"Name": "no"},
            )

            # Connect to shared network if using isolated network
            if network_id:
                try:
                    shared_net = self._pool._client.networks.get(shared_network_name)
                    await asyncio.to_thread(shared_net.connect, container)
                except OSError:
                    logger.debug("Failed to connect warm container to shared network")

            # Update DB
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(container_id=container.id, network_id=network_id)
                )
                await session.commit()

            logger.info("Warm container created: %s", container_name)

        except (OSError, RuntimeError) as exc:
            logger.error("Failed to create warm container: %s", exc)

    async def _count_warm(self) -> int:
        """Count containers in warm status."""
        async with async_session_maker() as session:
            result = await session.execute(select(Sandbox).where(Sandbox.status == self.WARM_STATUS))
            return len(result.scalars().all())
