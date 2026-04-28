"""Docker SDK wrapper for Swarm management.

Provides async-safe access to the Docker Engine API via the docker-py SDK.
Replaces all subprocess.run(['docker', ...]) calls.
No Docker CLI binary required.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    name: str
    replicas: int
    desired_replicas: int
    image: str
    image_digest: str  # sha256:... or empty
    running_tasks: int
    nodes: list[str] = field(default_factory=list)


@dataclass
class ContainerStats:
    container_id: str
    name: str
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class NodeInfo:
    id: str
    hostname: str
    role: str  # manager or worker
    status: str  # ready, down, etc.
    availability: str  # active, pause, drain
    labels: dict[str, str] = field(default_factory=dict)


def _get_client() -> docker.DockerClient:
    """Get a Docker client connected to the local socket."""
    return docker.from_env(timeout=15)


def _is_swarm_manager(client: docker.DockerClient) -> bool:
    """Return True only when this Docker socket can manage Swarm services."""
    try:
        swarm = client.info().get("Swarm", {})
    except (DockerException, APIError):
        return False
    return bool(swarm.get("ControlAvailable"))


async def _run_sync(func, *args, **kwargs) -> Any:
    """Run a blocking Docker SDK call in a thread."""
    return await asyncio.to_thread(functools.partial(func, *args, **kwargs))


# --- Service operations ---


def _parse_service(svc) -> ServiceInfo:
    """Extract ServiceInfo from a docker SDK service object."""
    attrs = svc.attrs
    spec = attrs.get("Spec", {})
    task_template = spec.get("TaskTemplate", {})
    container_spec = task_template.get("ContainerSpec", {})
    mode = spec.get("Mode", {})
    replicated = mode.get("Replicated", {})
    desired = replicated.get("Replicas", 1)

    image_full = container_spec.get("Image", "")
    image_ref = image_full.split("@")[0] if "@" in image_full else image_full
    image_digest = ""
    if "@sha256:" in image_full:
        image_digest = image_full.split("@sha256:")[-1][:64]

    # Count running tasks
    running_tasks = 0
    task_nodes: list[str] = []
    try:
        tasks = svc.tasks(filters={"desired-state": "running"})
        for task in tasks:
            task_status = task.get("Status", {}).get("State", "")
            if task_status == "running":
                running_tasks += 1
                node_id = task.get("NodeID", "")
                if node_id:
                    task_nodes.append(node_id)
    except Exception:
        logger.debug("Failed to enumerate tasks for service %s", svc.name, exc_info=True)

    return ServiceInfo(
        name=svc.name,
        replicas=running_tasks,
        desired_replicas=desired,
        image=image_ref,
        image_digest=image_digest,
        running_tasks=running_tasks,
        nodes=task_nodes,
    )


async def list_services() -> list[ServiceInfo]:
    """List all Swarm services with replica counts and images."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return []
            svcs = await _run_sync(client.services.list)
            return [_parse_service(s) for s in svcs]
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to list services: %s", exc)
        return []


async def get_service(name: str) -> ServiceInfo | None:
    """Get info for a specific service."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return None
            svc = await _run_sync(client.services.get, name)
            return _parse_service(svc)
        finally:
            client.close()
    except NotFound:
        return None
    except (DockerException, APIError) as exc:
        logger.warning("Failed to get service %s: %s", name, exc)
        return None


async def scale_service(name: str, replicas: int, detach: bool = True) -> bool:
    """Scale a service to N replicas."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return False
            svc = await _run_sync(client.services.get, name)
            await _run_sync(svc.scale, replicas)
            return True
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.error("Failed to scale %s to %d: %s", name, replicas, exc)
        return False


async def restart_service(name: str, detach: bool = True) -> bool:
    """Force-restart a service (rolling update with --force)."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return False
            svc = await _run_sync(client.services.get, name)
            # force_update increments the ForceUpdate counter triggering a re-deploy
            spec = svc.attrs.get("Spec", {})
            task_template = spec.get("TaskTemplate", {})
            current_force = task_template.get("ForceUpdate", 0)
            await _run_sync(svc.update, force_update=current_force + 1)
            return True
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.error("Failed to restart %s: %s", name, exc)
        return False


async def update_service_image(name: str, image: str, registry_auth: bool = True) -> bool:
    """Update a service to a new image (rolling update)."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return False
            svc = await _run_sync(client.services.get, name)
            spec = svc.attrs.get("Spec", {})
            task_template = spec.get("TaskTemplate", {})
            current_force = task_template.get("ForceUpdate", 0)
            await _run_sync(
                svc.update,
                image=image,
                force_update=current_force + 1,
                fetch_current_spec=True,
            )
            return True
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.error("Failed to update image for %s: %s", name, exc)
        return False


async def rollback_service(name: str) -> bool:
    """Rollback a service to its previous spec using Docker Swarm's built-in rollback.

    Uses the ``rollback`` parameter on the low-level API ``update_service``
    call, which tells the Swarm manager to revert to ``PreviousSpec``.
    """
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return False
            svc = await _run_sync(client.services.get, name)
            version = svc.attrs["Version"]["Index"]
            # Use the low-level API endpoint with rollback=True.
            # This mirrors ``docker service update --rollback <svc>``.
            await _run_sync(
                client.api.update_service,
                svc.id,
                version,
                svc.attrs.get("PreviousSpec", svc.attrs["Spec"]),
                rollback=True,
            )
            logger.info("Rolled back service %s to previous spec", name)
            return True
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.error("Failed to rollback %s: %s", name, exc)
        return False


# --- Metrics ---


async def get_service_logs(name: str, tail: int = 50) -> str:
    """Get recent logs from a service."""
    try:
        client = _get_client()
        try:
            svc = await _run_sync(client.services.get, name)
            log_bytes = await _run_sync(
                svc.logs, stdout=True, stderr=True, tail=tail, timestamps=True,
            )
            if isinstance(log_bytes, bytes):
                return log_bytes.decode("utf-8", errors="replace")
            # Generator of bytes chunks
            return b"".join(log_bytes).decode("utf-8", errors="replace")
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to get logs for %s: %s", name, exc)
        return ""


def _calc_cpu_percent(stats: dict) -> float:
    """Calculate CPU percentage from docker stats response."""
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})

    cpu_usage = cpu_stats.get("cpu_usage", {})
    precpu_usage = precpu_stats.get("cpu_usage", {})

    cpu_delta = cpu_usage.get("total_usage", 0) - precpu_usage.get("total_usage", 0)
    system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

    if system_delta > 0 and cpu_delta >= 0:
        online_cpus = cpu_stats.get("online_cpus") or len(cpu_usage.get("percpu_usage", [])) or 1
        return (cpu_delta / system_delta) * online_cpus * 100.0
    return 0.0


async def get_container_stats() -> list[ContainerStats]:
    """Get CPU/memory stats for all running containers (non-stream)."""
    results: list[ContainerStats] = []
    try:
        client = _get_client()
        try:
            containers = await _run_sync(client.containers.list)
            for container in containers:
                try:
                    stats = await _run_sync(container.stats, stream=False)
                    mem_stats = stats.get("memory_stats", {})
                    mem_usage = mem_stats.get("usage", 0)
                    mem_limit = mem_stats.get("limit", 0)

                    results.append(ContainerStats(
                        container_id=container.short_id,
                        name=container.name,
                        cpu_percent=_calc_cpu_percent(stats),
                        memory_mb=mem_usage / (1024 * 1024),
                        memory_limit_mb=mem_limit / (1024 * 1024),
                        labels=dict(container.labels or {}),
                    ))
                except Exception as exc:
                    logger.debug("Stats failed for container %s: %s", container.name, exc)
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to get container stats: %s", exc)
    return results


async def list_running_containers() -> list[ContainerStats]:
    """List running containers without expensive Docker stats collection."""
    results: list[ContainerStats] = []
    try:
        client = _get_client()
        try:
            containers = await _run_sync(client.containers.list)
            for container in containers:
                results.append(ContainerStats(
                    container_id=container.short_id,
                    name=container.name,
                    cpu_percent=0.0,
                    memory_mb=0.0,
                    memory_limit_mb=0.0,
                    labels=dict(container.labels or {}),
                ))
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to list running containers: %s", exc)
    return results


async def get_service_task_nodes(name: str) -> list[str]:
    """Get hostnames of nodes where a service's tasks are running."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return []
            svc = await _run_sync(client.services.get, name)
            tasks = await _run_sync(svc.tasks, filters={"desired-state": "running"})
            node_ids = {t.get("NodeID", "") for t in tasks if t.get("Status", {}).get("State") == "running"}
            node_ids.discard("")

            # Resolve node IDs to hostnames
            hostnames: list[str] = []
            for nid in node_ids:
                try:
                    node = await _run_sync(client.nodes.get, nid)
                    desc = node.attrs.get("Description", {})
                    hostnames.append(desc.get("Hostname", nid))
                except Exception:
                    hostnames.append(nid)
            return hostnames
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to get task nodes for %s: %s", name, exc)
        return []


async def count_running_containers() -> int:
    """Count running containers on this node."""
    try:
        client = _get_client()
        try:
            containers = await _run_sync(client.containers.list)
            return len(containers)
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.debug("Failed to count containers: %s", exc)
        return 0


# --- Node operations ---


async def list_nodes() -> list[NodeInfo]:
    """List all Swarm nodes."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return []
            nodes = await _run_sync(client.nodes.list)
            result: list[NodeInfo] = []
            for node in nodes:
                attrs = node.attrs
                spec = attrs.get("Spec", {})
                desc = attrs.get("Description", {})
                status = attrs.get("Status", {})
                result.append(NodeInfo(
                    id=attrs.get("ID", ""),
                    hostname=desc.get("Hostname", ""),
                    role=spec.get("Role", "worker"),
                    status=status.get("State", "unknown"),
                    availability=spec.get("Availability", "active"),
                    labels=spec.get("Labels", {}),
                ))
            return result
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Failed to list nodes: %s", exc)
        return []


async def update_node_labels(
    node_id: str, labels: dict[str, str], remove_labels: list[str] | None = None,
) -> bool:
    """Update labels on a Swarm node."""
    try:
        client = _get_client()
        try:
            if not _is_swarm_manager(client):
                return False
            node = await _run_sync(client.nodes.get, node_id)
            spec = node.attrs.get("Spec", {})
            current_labels = dict(spec.get("Labels", {}))

            # Remove labels
            if remove_labels:
                for lbl in remove_labels:
                    current_labels.pop(lbl, None)

            # Add/update labels
            current_labels.update(labels)

            node_spec = {
                "Availability": spec.get("Availability", "active"),
                "Role": spec.get("Role", "worker"),
                "Labels": current_labels,
            }
            node_version = node.attrs.get("Version", {}).get("Index", 0)
            await _run_sync(
                client.api.update_node,
                node.id,
                node_version,
                node_spec,
            )
            return True
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.error("Failed to update labels for node %s: %s", node_id, exc)
        return False


# --- Cleanup operations ---


async def prune_containers(filters: dict | None = None) -> dict:
    """Prune stopped containers."""
    try:
        client = _get_client()
        try:
            result = await _run_sync(client.containers.prune, filters=filters or {})
            return result
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Container prune failed: %s", exc)
        return {}


async def prune_images(filters: dict | None = None) -> dict:
    """Prune dangling images."""
    try:
        client = _get_client()
        try:
            result = await _run_sync(client.images.prune, filters=filters or {})
            return result
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Image prune failed: %s", exc)
        return {}


async def prune_volumes() -> dict:
    """Prune orphaned volumes."""
    try:
        client = _get_client()
        try:
            result = await _run_sync(client.volumes.prune)
            return result
        finally:
            client.close()
    except (DockerException, APIError) as exc:
        logger.warning("Volume prune failed: %s", exc)
        return {}


# --- Registry operations ---


async def get_registry_digest(image_ref: str) -> str | None:
    """Get the latest digest for an image from the registry.

    Uses the Docker SDK's distribution API first, then falls back to
    direct v2 HTTP API.
    """
    # Strip any existing @sha256: digest
    if "@sha256:" in image_ref:
        image_ref = image_ref.split("@")[0]

    # Try Docker SDK registry data first
    try:
        client = _get_client()
        try:
            reg_data = await _run_sync(client.images.get_registry_data, image_ref)
            digest = reg_data.attrs.get("Descriptor", {}).get("digest", "")
            if not digest:
                digest = reg_data.id or ""
            if digest.startswith("sha256:"):
                return digest.split("sha256:")[-1][:64]
        finally:
            client.close()
    except Exception as exc:
        logger.debug("SDK registry data failed for %s: %s", image_ref, exc)

    # Fallback: direct v2 HTTP API
    return await _get_registry_digest_v2(image_ref)


async def _get_registry_digest_v2(image_ref: str) -> str | None:
    """Fallback: query registry v2 API directly for digest."""
    parts = image_ref.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0]):
        registry = parts[0]
        repo_tag = parts[1]
    else:
        return None

    if ":" in repo_tag:
        repo, tag = repo_tag.rsplit(":", 1)
    else:
        repo, tag = repo_tag, "latest"

    import httpx

    for scheme in ("https", "http"):
        url = f"{scheme}://{registry}/v2/{repo}/manifests/{tag}"
        try:
            async with httpx.AsyncClient(timeout=10) as http_client:
                resp = await http_client.head(
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


# --- Availability check ---


async def is_docker_available() -> bool:
    """Check if Docker socket is accessible."""
    try:
        client = _get_client()
        try:
            await _run_sync(client.ping)
            return True
        finally:
            client.close()
    except Exception:
        return False
