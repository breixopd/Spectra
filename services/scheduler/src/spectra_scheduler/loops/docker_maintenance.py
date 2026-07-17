"""Docker pruning and rolling image-update loops (scheduler-owned shell)."""

import logging

import spectra_scheduler.locking as _sched_lock
from spectra_persistence.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _DOCKER_CLEANUP_LOCK_ID, _IMAGE_UPDATE_LOCK_ID

logger = logging.getLogger("spectra_scheduler")


class SchedulerDockerMaintenanceMixin:
    running: bool

    async def _docker_cleanup(self):
        """Conservatively clean Docker resources owned by the scheduler host."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            await async_ops.sleep(settings.DOCKER_CLEANUP_INTERVAL)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _DOCKER_CLEANUP_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("Docker cleanup lock not acquired — skipping")
                        continue

                    from spectra_scaling.docker_client import (
                        prune_containers,
                        prune_images,
                        prune_volumes,
                    )

                    # Keep recent stopped containers for diagnosis and only remove
                    # untagged images. Docker image prune includes non-dangling
                    # unused images unless ``dangling=true`` is explicit.
                    await prune_containers(filters={"until": ["48h"]})
                    await prune_images(filters={"dangling": ["true"], "until": ["168h"]})
                    # Volumes can carry databases, backups, and operator data. They
                    # are never pruned by default; opt-in only targets project labels.
                    if settings.DOCKER_PRUNE_VOLUMES:
                        await prune_volumes(filters={"label": ["spectra.managed=true"]})
                    # Prune only old exited Swarm task containers.
                    await prune_containers(filters={
                        "label": ["com.docker.swarm.task"],
                        "status": ["exited"],
                        "until": ["168h"],
                    })
                    logger.info("Docker cleanup completed: pruned safe containers and dangling images")
            except Exception as e:
                logger.warning("Docker cleanup failed: %s", e)

    async def _image_update_check(self):
        """Check for new image versions and trigger rolling updates."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            await async_ops.sleep(settings.IMAGE_CHECK_INTERVAL)
            if not self.running:
                break
            if not settings.IMAGE_AUTO_UPDATE:
                logger.debug("Image auto-update disabled; skipping registry polling")
                continue
            try:
                async with _sched_lock.advisory_lock_owner(
                    _IMAGE_UPDATE_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("Image update lock not acquired — skipping")
                        continue

                    from spectra_scaling.image_updater import check_and_update_services

                    results = await check_and_update_services(apply=settings.IMAGE_AUTO_UPDATE)
                    if results:
                        for r in results:
                            if r.success and not r.error:
                                logger.info("Auto-updated %s: %s → %s", r.service, r.old_digest, r.new_digest)
                                await self._send_update_notification(
                                    f"Auto-updated {r.service}",
                                    f"Digest: {r.old_digest} → {r.new_digest}",
                                    level="info",
                                )
                            elif not r.success:
                                logger.error("Auto-update failed for %s: %s", r.service, r.error)
                                await self._send_update_notification(
                                    f"Auto-update failed: {r.service}",
                                    r.error,
                                    level="error",
                                )
            except Exception:
                logger.exception("Image update check error")

    async def _send_update_notification(self, title: str, message: str, *, level: str = "info") -> None:
        """Send image update notification via configured channels."""
        try:
            from spectra_system.notifications import send_notification

            await send_notification(
                title=title,
                message=message,
                priority="normal" if level == "info" else "urgent",
                tags=["image-update", level],
            )
        except Exception as e:
            logger.warning("Image update notification failed: %s", e)
