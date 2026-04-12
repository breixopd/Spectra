"""Automatic image update watcher.

Polls the configured container registry for new image digests and
triggers Swarm rolling updates when a newer version is available.
Runs as a scheduler task on the Swarm manager node.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Services we manage auto-updates for (mapped to their full image refs)
MANAGED_SERVICES = {
    "spectra_app",
    "spectra_ai-svc",
    "spectra_scheduler",
    "spectra_caddy",
    "spectra_worker",
}

# Don't auto-update third-party images (db, redis, garage, clickhouse, tensorzero)
# — those require manual version bumps and migration steps.

# Module-level cache of last-seen digests for the status endpoint
_last_check: dict[str, dict] = {}


@dataclass
class ImageUpdateResult:
    service: str
    old_digest: str
    new_digest: str
    success: bool
    error: str = ""


async def check_and_update_services(*, apply: bool = True) -> list[ImageUpdateResult]:
    """Check all managed services for image updates and optionally apply them.

    When *apply* is False the check still runs and populates the status
    cache but skips the rolling update step.

    Returns a list of update results (empty if nothing changed).
    """
    from app.services.scaling.docker_client import (
        get_registry_digest,
        get_service,
        update_service_image,
    )

    results: list[ImageUpdateResult] = []

    for service in sorted(MANAGED_SERVICES):
        try:
            svc_info = await get_service(service)
            if not svc_info:
                logger.debug("Could not get service info for %s, skipping", service)
                continue

            image_ref = svc_info.image
            if not image_ref:
                continue

            running_digest = svc_info.image_digest or None
            registry_digest = await get_registry_digest(image_ref)

            if not registry_digest:
                logger.debug("Could not get registry digest for %s (%s)", service, image_ref)
                continue

            # Populate status cache regardless of apply
            _last_check[service] = {
                "image": image_ref,
                "running_digest": running_digest or "unknown",
                "registry_digest": registry_digest,
                "update_available": bool(running_digest and running_digest != registry_digest),
                "checked_at": time.time(),
            }

            if not running_digest or running_digest == registry_digest:
                continue  # Up to date

            if not apply:
                results.append(ImageUpdateResult(
                    service=service,
                    old_digest=(running_digest or "unknown")[:12],
                    new_digest=registry_digest[:12],
                    success=True,
                    error="dry-run (auto-update disabled)",
                ))
                continue

            logger.info(
                "Image update available for %s: %s -> %s",
                service, (running_digest or "unknown")[:12], registry_digest[:12],
            )

            # Trigger rolling update
            ok = await update_service_image(
                service, f"{image_ref}@sha256:{registry_digest}",
            )

            result = ImageUpdateResult(
                service=service,
                old_digest=(running_digest or "unknown")[:12],
                new_digest=registry_digest[:12],
                success=ok,
                error="" if ok else "service update failed",
            )
            results.append(result)

            if ok:
                logger.info("Updated %s to %s", service, registry_digest[:12])
            else:
                logger.error("Failed to update %s", service)

            # Small delay between services for safety
            await asyncio.sleep(5)

        except Exception as exc:
            logger.exception("Error checking updates for %s", service)
            results.append(ImageUpdateResult(
                service=service, old_digest="", new_digest="",
                success=False, error=str(exc)[:200],
            ))

    return results


def get_update_status() -> dict[str, dict]:
    """Return the cached update status for all managed services."""
    return dict(_last_check)
