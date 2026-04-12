"""Automatic image update watcher.

Polls the configured container registry for new image digests and
triggers Swarm rolling updates when a newer version is available.
Runs as a scheduler task on the Swarm manager node.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field

import httpx

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


async def _run_cmd(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a command via subprocess, return (success, output)."""
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout.strip() or result.stderr.strip()
        return result.returncode == 0, out
    except Exception as e:
        return False, str(e)


async def _get_running_digest(service: str) -> str | None:
    """Get the image digest currently running for a Swarm service."""
    ok, out = await _run_cmd([
        "docker", "service", "inspect", service,
        "--format", "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
    ])
    if ok and "@sha256:" in out:
        return out.split("@sha256:")[-1][:64]
    # If no pinned digest, get the image reference
    if ok:
        return out  # e.g. "registry/image:tag"
    return None


async def _get_registry_digest(image_ref: str) -> str | None:
    """Query the registry for the latest digest of an image tag.

    Uses ``docker manifest inspect`` which works with the Docker socket
    and respects registry auth.
    """
    # Strip any existing @sha256: digest
    if "@sha256:" in image_ref:
        image_ref = image_ref.split("@")[0]

    ok, out = await _run_cmd([
        "docker", "manifest", "inspect", image_ref, "--verbose",
    ], timeout=15)

    if not ok:
        # Fallback: use Docker API directly via registry v2
        return await _get_registry_digest_v2(image_ref)

    # Parse digest from manifest inspect output
    try:
        data = json.loads(out)
        if isinstance(data, list):
            data = data[0]
        descriptor = data.get("Descriptor", {})
        digest = descriptor.get("digest", "")
        if digest.startswith("sha256:"):
            return digest.split("sha256:")[-1][:64]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


async def _get_registry_digest_v2(image_ref: str) -> str | None:
    """Fallback: query registry v2 API directly for digest."""
    # Parse registry/repo:tag
    parts = image_ref.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0]):
        registry = parts[0]
        repo_tag = parts[1]
    else:
        return None  # Can't parse

    if ":" in repo_tag:
        repo, tag = repo_tag.rsplit(":", 1)
    else:
        repo, tag = repo_tag, "latest"

    # Try HTTP first (insecure registry), then HTTPS
    for scheme in ("http", "https"):
        url = f"{scheme}://{registry}/v2/{repo}/manifests/{tag}"
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as client:  # noqa: S501
                resp = await client.head(
                    url,
                    headers={
                        "Accept": "application/vnd.docker.distribution.manifest.v2+json, "
                                  "application/vnd.oci.image.manifest.v1+json"
                    },
                )
                if resp.status_code == 200:
                    digest = resp.headers.get("Docker-Content-Digest", "")
                    if digest.startswith("sha256:"):
                        return digest.split("sha256:")[-1][:64]
        except Exception:
            continue
    return None


async def _get_service_image(service: str) -> str | None:
    """Get the image reference (without digest) for a service."""
    ok, out = await _run_cmd([
        "docker", "service", "inspect", service,
        "--format", "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
    ])
    if ok and out:
        # Strip @sha256:... if present
        return out.split("@")[0] if "@" in out else out
    return None


async def check_and_update_services(*, apply: bool = True) -> list[ImageUpdateResult]:
    """Check all managed services for image updates and optionally apply them.

    When *apply* is False the check still runs and populates the status
    cache but skips the ``docker service update`` step.

    Returns a list of update results (empty if nothing changed).
    """
    results: list[ImageUpdateResult] = []

    for service in sorted(MANAGED_SERVICES):
        try:
            image_ref = await _get_service_image(service)
            if not image_ref:
                logger.debug("Could not get image ref for %s, skipping", service)
                continue

            running_digest = await _get_running_digest(service)
            registry_digest = await _get_registry_digest(image_ref)

            if not registry_digest:
                logger.debug("Could not get registry digest for %s (%s)", service, image_ref)
                continue

            # Populate status cache regardless of apply
            _last_check[service] = {
                "image": image_ref,
                "running_digest": running_digest or "unknown",
                "registry_digest": registry_digest,
                "update_available": bool(running_digest and running_digest != registry_digest and running_digest != image_ref),
                "checked_at": time.time(),
            }

            if not running_digest or running_digest == registry_digest:
                continue  # Up to date

            # Also skip if running_digest is the image ref itself (no digest pinned)
            if running_digest == image_ref:
                # Can't compare — force update to pin digest
                pass

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
            ok, out = await _run_cmd([
                "docker", "service", "update",
                "--image", f"{image_ref}@sha256:{registry_digest}",
                "--with-registry-auth",
                service,
            ], timeout=120)

            result = ImageUpdateResult(
                service=service,
                old_digest=(running_digest or "unknown")[:12],
                new_digest=registry_digest[:12],
                success=ok,
                error="" if ok else out[:200],
            )
            results.append(result)

            if ok:
                logger.info("Updated %s to %s", service, registry_digest[:12])
            else:
                logger.error("Failed to update %s: %s", service, out[:200])

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
