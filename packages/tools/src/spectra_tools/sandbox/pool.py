"""Sandbox container pool — manages lifecycle of per-mission ephemeral containers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    from docker.errors import APIError, ContainerError, DockerException, ImageNotFound, NotFound
except ImportError:
    DockerException = APIError = ContainerError = ImageNotFound = NotFound = OSError  # type: ignore[assignment,misc]
from sqlalchemy import select, text, update

from spectra_common.config import get_settings
from spectra_persistence.database import async_session_maker
from spectra_persistence.models.infrastructure import Sandbox
from spectra_tools.sandbox._utils import sandbox_database_role_name, sandbox_database_url
from spectra_tools.sandbox.models import SandboxInfo

logger = logging.getLogger(__name__)


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

    def _resolve_shared_network_name(self, preferred_name: str) -> str:
        """Resolve compose-prefixed network names for ad hoc sandbox containers."""
        if not self.available:
            return preferred_name
        try:
            self._client.networks.get(preferred_name)
            return preferred_name
        except (APIError, NotFound):
            pass

        try:
            for network in self._client.networks.list():
                name = getattr(network, "name", "")
                if name == preferred_name or name.endswith(f"_{preferred_name}"):
                    return name
        except (APIError, DockerException):
            logger.debug("Failed to enumerate docker networks when resolving %s", preferred_name)
        return preferred_name

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

    async def create(
        self,
        mission_id: str,
        *,
        resource_tier: str = "medium",
        vpn_config_path: str | None = None,
        user_id: str | None = None,
    ) -> SandboxInfo:
        """Create a new sandbox container for a mission.

        Raises:
            RuntimeError: If Docker is unavailable or max containers reached.
        """
        if not self.available:
            raise RuntimeError("Docker is not available — cannot create sandbox")

        settings = get_settings()
        if not settings.SANDBOX_NETWORK_ISOLATION:
            raise RuntimeError("SANDBOX_NETWORK_ISOLATION must remain enabled")

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
        # The full UUID prevents collisions once the platform has run more
        # than a modest number of missions (the first eight characters do
        # not provide enough uniqueness for long-lived deployments).
        sandbox_name_suffix = mission_id.replace("-", "")
        container_name = f"spectra-sandbox-{sandbox_name_suffix}"
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

        sandbox_role_name = sandbox_database_role_name(mission_id)
        try:
            sandbox_dsn = await self._provision_database_access(sandbox_role_name)
        except RuntimeError as exc:
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox).where(Sandbox.id == sandbox_id).values(status="error", error=str(exc)[:500])
                )
                await session.commit()
            raise

        # Mission sandboxes receive only their dedicated least-privilege queue
        # credential; the platform's primary database secret never crosses this
        # trust boundary.
        environment = {
            "QUEUE_NAME": queue_name,
            "IS_TOOLS_CONTAINER": "true",
            "CONNECT_BACK_HOST": settings.CONNECT_BACK_HOST,
            "DATABASE_URL": sandbox_dsn,
            "DATA_ROOT": "/app/data",
        }

        # Sandboxes execute target-facing tools. Keep their writable state
        # ephemeral instead of exposing global app-data, tool-binary, or
        # plugin volumes. The promoted worker image already contains the
        # approved plugin definitions it needs.
        import docker.types

        mounts: list[Any] = []

        # Mount VPN config if provided
        if vpn_config_path:
            mounts.append(
                docker.types.Mount(
                    target="/app/vpn_configs/mission.conf", source=vpn_config_path, type="bind", read_only=True
                )
            )

        # A sandbox needs a private egress network for targets plus the small,
        # internal database-only network configured above. Joining the general
        # application backend would expose Redis, internal APIs, and storage
        # credentials to target-facing code.
        sandbox_network_id: str | None = None
        shared_network_name = self._resolve_shared_network_name(settings.SANDBOX_NETWORK)

        net_name = f"spectra-sandbox-{sandbox_name_suffix}"
        net_labels = {"spectra.sandbox": "true", "spectra.mission_id": mission_id}
        try:
            net = await asyncio.to_thread(
                self._client.networks.create,
                net_name,
                driver="bridge",
                labels=net_labels,
            )
            sandbox_network_id = net.id
            logger.info("Created isolated network %s for mission %s", net_name, mission_id[:8])
        except (APIError, DockerException, OSError) as exc:
            logger.error("Failed to create isolated network for mission %s: %s", mission_id[:8], exc)
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox).where(Sandbox.id == sandbox_id).values(status="error", error=str(exc)[:500])
                )
                await session.commit()
            await self._revoke_database_access(sandbox_role_name)
            raise RuntimeError(f"Sandbox network creation failed: {exc}") from exc

        container: Any | None = None
        try:
            capabilities: list[str] = []
            devices: list[str] = []
            if vpn_config_path:
                capabilities = ["NET_ADMIN", "NET_RAW"]
                devices = ["/dev/net/tun"]
            elif settings.SANDBOX_ALLOW_RAW_NETWORK:
                capabilities = ["NET_RAW"]

            container = await asyncio.to_thread(
                self._client.containers.run,
                image=settings.SANDBOX_IMAGE,
                name=container_name,
                detach=True,
                network=net_name,
                environment=environment,
                mounts=mounts,
                mem_limit=memory_limit,
                memswap_limit=memory_limit,  # No swap
                cpu_shares=cpu_shares,
                labels={
                    "spectra.sandbox": "true",
                    "spectra.mission_id": mission_id,
                    "spectra.queue_name": queue_name,
                },
                cap_add=capabilities,
                cap_drop=["ALL"],
                pids_limit=256,
                read_only=True,
                security_opt=["no-new-privileges:true"],
                tmpfs={
                    "/tmp": "rw,noexec,nosuid,nodev,size=2G",
                    "/var/tmp": "rw,noexec,nosuid,nodev,size=512m",
                    "/app/data": "rw,noexec,nosuid,nodev,size=512m",
                },
                devices=devices,
                restart_policy={"Name": "no"},
            )
            if container is None:
                raise RuntimeError("Docker did not return a sandbox container")

            # The dedicated database network must be available. Continuing
            # without it would create a sandbox that cannot process its queue.
            shared_net = await asyncio.to_thread(self._client.networks.get, shared_network_name)
            await asyncio.to_thread(shared_net.connect, container)
            logger.debug("Connected sandbox %s to database network %s", container_name, shared_network_name)

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
                container_name,
                queue_name,
                mission_id[:8],
                bool(sandbox_network_id),
            )
            return info

        except (APIError, ContainerError, ImageNotFound, DockerException, OSError, RuntimeError) as exc:
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except (APIError, DockerException, OSError):
                    logger.debug("Failed to remove sandbox after creation failure", exc_info=True)
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
                    update(Sandbox).where(Sandbox.id == sandbox_id).values(status="error", error=str(exc)[:500])
                )
                await session.commit()
            await self._revoke_database_access(sandbox_role_name)
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

        await self._revoke_database_access(sandbox_database_role_name(mission_id))

        async with async_session_maker() as session:
            await session.execute(
                update(Sandbox).where(Sandbox.id == row.id).values(status="destroyed", destroyed_at=datetime.now(UTC))
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
            resource_tier=row.resource_tier or "medium",
            network_id=row.network_id,
            created_at=row.created_at,
        )

    async def reconcile_orphans(self) -> int:
        """Remove only labelled Docker resources without an active sandbox record.

        This is safe to run from periodic maintenance and service startup. In
        particular, it never stops a sandbox merely because a control-plane
        replica restarted; active database rows remain the ownership source of
        truth until their normal lifecycle or watchdog cleanup completes.
        """
        creation_cutoff = datetime.now(UTC) - timedelta(minutes=5)
        async with async_session_maker() as session:
            stale_rows = await session.execute(
                select(Sandbox).where(
                    Sandbox.status == "creating",
                    Sandbox.created_at < creation_cutoff,
                )
            )
            stale_creations = list(stale_rows.scalars().all())
            for stale in stale_creations:
                stale.status = "error"
                stale.error = "Sandbox creation did not complete within five minutes"
            if stale_creations:
                await session.commit()

            rows = await session.execute(
                select(Sandbox.mission_id, Sandbox.container_id, Sandbox.network_id).where(
                    Sandbox.status.in_(["creating", "running", "stopping"])
                )
            )
            active_rows = rows.all()
            active_container_ids = {container_id for _mission_id, container_id, _network_id in active_rows if container_id}
            active_network_ids = {network_id for _mission_id, _container_id, network_id in active_rows if network_id}
            active_role_names = {
                sandbox_database_role_name(str(mission_id))
                for mission_id, _container_id, _network_id in active_rows
            }

        revoked_roles = await self._reconcile_database_roles(active_role_names)
        if not self.available:
            return revoked_roles

        def _reconcile() -> int:
            removed = 0
            containers = self._client.containers.list(all=True, filters={"label": "spectra.sandbox=true"})
            for container in containers:
                if container.id in active_container_ids:
                    continue
                container.remove(force=True)
                removed += 1

            networks = self._client.networks.list(filters={"label": "spectra.sandbox=true"})
            for network in networks:
                if network.id in active_network_ids:
                    continue
                network.reload()
                if network.attrs.get("Containers"):
                    continue
                network.remove()
            return removed

        try:
            removed = await asyncio.to_thread(_reconcile)
        except (APIError, DockerException, OSError) as exc:
            logger.warning("Sandbox orphan reconciliation failed: %s", exc)
            return revoked_roles
        if removed:
            logger.info("Removed %d untracked sandbox containers", removed)
        return removed + revoked_roles

    async def health_check(self) -> dict[str, Any]:
        """Check health of all running sandboxes. Reap expired ones."""
        settings = get_settings()
        configured = bool(settings.DATABASE_URL.get_secret_value())
        result: dict[str, Any] = {
            "available": self.available,
            "configured": configured,
            "status": "healthy" if self.available and configured else "degraded",
            "sandboxes": {},
        }

        if not self.available or not configured:
            return result

        async with async_session_maker() as session:
            rows = await session.execute(select(Sandbox).where(Sandbox.status == "running"))
            running = list(rows.scalars().all())

        now = datetime.now(UTC)
        for row in running:
            age_seconds = (now - row.created_at).total_seconds()
            alive = self._is_container_alive(row.container_id)

            if not alive or age_seconds > settings.SANDBOX_MAX_LIFETIME:
                reason = "expired" if alive else "dead"
                logger.warning(
                    "Reaping sandbox %s (mission=%s, reason=%s)",
                    row.container_name,
                    row.mission_id[:8],
                    reason,
                )
                await self.destroy(row.mission_id)
                result["sandboxes"][row.mission_id] = reason
            else:
                result["sandboxes"][row.mission_id] = "healthy"

        return result

    async def _provision_database_access(self, role_name: str) -> str:
        """Create a one-mission database role limited to its queue rows."""
        settings = get_settings()
        admin_url = settings.DATABASE_URL.get_secret_value()
        password = secrets.token_urlsafe(32)
        sandbox_dsn = sandbox_database_url(admin_url, role_name=role_name, password=password)

        try:
            async with async_session_maker() as session:
                create_role_sql = (
                    await session.execute(
                        text(
                            f"""
                            SELECT format(
                                'CREATE ROLE {role_name} LOGIN PASSWORD %L '
                                'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION '
                                'CONNECTION LIMIT 1',
                                CAST(:password AS text)
                            )
                            """
                        ),
                        {"password": password},
                    )
                ).scalar_one()
                await session.execute(
                    text(
                        create_role_sql
                    )
                )
                await session.execute(text(f"GRANT USAGE ON SCHEMA public TO {role_name}"))
                await session.execute(text(f"GRANT SELECT, UPDATE ON TABLE job_queue TO {role_name}"))
                await session.commit()
        except Exception as exc:
            logger.error("Failed to provision sandbox database role %s: %s", role_name, exc)
            raise RuntimeError("Sandbox database role provisioning failed") from exc

        return sandbox_dsn

    async def _reconcile_database_roles(self, active_role_names: set[str]) -> int:
        """Remove credentials left by a process crash after sandbox shutdown."""
        try:
            async with async_session_maker() as session:
                rows = await session.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'spectra_sandbox_%'")
                )
                role_names = list(rows.scalars().all())
        except Exception:
            logger.warning("Failed to enumerate sandbox database roles", exc_info=True)
            return 0

        revoked = 0
        for role_name in role_names:
            if not re.fullmatch(r"spectra_sandbox_[0-9a-f]{32}", role_name):
                continue
            if role_name in active_role_names:
                continue
            if await self._revoke_database_access(role_name):
                revoked += 1
        if revoked:
            logger.info("Revoked %d stale sandbox database role(s)", revoked)
        return revoked

    async def _revoke_database_access(self, role_name: str) -> bool:
        """Drop a sandbox role after its container has been removed."""
        try:
            async with async_session_maker() as session:
                # PostgreSQL will not drop a role while grants still depend on
                # it. Revoke first and commit that safety boundary even if an
                # active connection temporarily prevents the final DROP.
                await session.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE job_queue FROM {role_name}"))
                await session.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {role_name}"))
                await session.commit()
                try:
                    await session.execute(text(f"DROP ROLE IF EXISTS {role_name}"))
                    await session.commit()
                    return True
                except Exception:
                    await session.rollback()
                    # A lingering TCP connection must not keep a former
                    # sandbox credential usable while the next cleanup retry
                    # waits for PostgreSQL to release it.
                    await session.execute(text(f"ALTER ROLE {role_name} NOLOGIN"))
                    await session.commit()
        except Exception:
            logger.warning("Failed to revoke sandbox database role %s", role_name, exc_info=True)
        return False

    # -- Private helpers --

    async def _count_running(self) -> int:
        """Count sandboxes in running or creating state."""
        async with async_session_maker() as session:
            result = await session.execute(select(Sandbox).where(Sandbox.status.in_(["creating", "running"])))
            return len(list(result.scalars().all()))

    def _is_container_alive(self, container_id: str) -> bool:
        """Check if a Docker container is still running."""
        if not self.available or not container_id:
            return False
        try:
            c = self._client.containers.get(container_id)
            return c.status == "running"
        except OSError:
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
            except OSError:
                logger.debug("Failed to stop container %s (may already be stopped)", name, exc_info=True)
            try:
                c = self._client.containers.get(container_id)
                c.remove(force=True)
            except OSError:
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
                    except OSError:
                        logger.debug(
                            "Failed to disconnect container %s from network %s",
                            cid[:12],
                            network_id[:12],
                            exc_info=True,
                        )
                net.remove()
                logger.info("Removed isolated network %s (sandbox=%s)", network_id[:12], sandbox_name)
            except OSError as exc:
                logger.debug("Network %s already removed or not found: %s", network_id[:12], exc)

        await asyncio.to_thread(_do_remove)
