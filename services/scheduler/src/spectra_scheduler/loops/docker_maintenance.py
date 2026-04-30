"""Docker pruning and rolling image-update loops (scheduler-owned shell)."""

import logging

import spectra_scheduler.locking as _sched_lock
from app.core.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _DOCKER_CLEANUP_LOCK_ID, _IMAGE_UPDATE_LOCK_ID

logger = logging.getLogger("spectra_scheduler")


class SchedulerDockerMaintenanceMixin:
    async def _docker_cleanup(self):
        """Weekly Docker resource cleanup — prune dangling images and exited containers."""
        from app.core.config import get_settings

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

                    from app.services.scaling.docker_client import (
                        prune_containers,
                        prune_images,
                        prune_volumes,
                    )

                    # Prune exited containers
                    await prune_containers(filters={"until": ["48h"]})
                    # Prune dangling images
                    await prune_images(filters={"until": ["168h"]})
                    # Prune dangling volumes (only truly orphaned)
                    await prune_volumes()
                    # Prune exited Swarm task containers
                    await prune_containers(filters={
                        "label": ["com.docker.swarm.task"],
                        "status": ["exited"],
                    })
                    logger.info("Docker cleanup completed: pruned containers, images, volumes, swarm tasks")
            except Exception as e:
                logger.warning("Docker cleanup failed: %s", e)

    async def _image_update_check(self):
        """Check for new image versions and trigger rolling updates."""
        from app.core.config import get_settings

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

                    from app.services.scaling.image_updater import check_and_update_services

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
            from app.services.notifications import send_notification

            await send_notification(
                title=title,
                message=message,
                priority="normal" if level == "info" else "urgent",
                tags=["image-update", level],
            )
        except Exception as e:
            logger.warning("Image update notification failed: %s", e)
