"""Shared platform health collection.

This module keeps health semantics in one place so public status, load
balancer probes, admin detail views, and tests do not drift apart.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_common._meta.version import __version__
from spectra_common.config import get_settings

HealthMap = dict[str, Any]

_HEALTHY_STATES = {"healthy", "ok", "running", "ready", "not_configured", "not configured", "disabled"}

# Simple in-memory TTL cache for health checks to avoid repeated probing
_health_cache: dict[str, tuple[float, HealthMap]] = {}
_HEALTH_CACHE_TTL_SECONDS = 10.0

# Reusable Redis client for health checks (initialised lazily)
_redis_client: Any = None
_DEGRADED_STATES = {"degraded", "warning", "fallback", "standby"}
_CONTROL_PLANE_HEALTH_HOSTS = {"app", "spectra-app", "scheduler", "worker", "ai-svc", "localhost", "127.0.0.1"}
_CONTROL_PLANE_SERVICE_TYPES = {"app", "api", "scheduler", "worker", "ai", "ai-svc"}


async def close_health_clients() -> None:
    """Close reusable clients owned by health checks."""
    global _redis_client
    if _redis_client is None:
        return
    client = _redis_client
    _redis_client = None
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is not None:
        result = close()
        if asyncio.iscoroutine(result):
            await result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _latency_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def _status_from_http(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "healthy"
    if 300 <= status_code < 500:
        return "degraded"
    return "unhealthy"


def _normalize_status(value: Any) -> str:
    status = str(value or "unknown").lower().replace(" ", "_")
    if status == "not_configured":
        return "not_configured"
    if status in {"unreachable", "error", "failed"}:
        return "unhealthy"
    if status in _HEALTHY_STATES:
        return "healthy" if status != "not configured" else "not_configured"
    if status in _DEGRADED_STATES or status.startswith("degraded"):
        return "degraded"
    if status in {"unhealthy", "unavailable", "disconnected"}:
        return "unhealthy"
    return status


def _is_control_plane_health_url(url: str, service_type: str, metadata: dict[str, Any]) -> bool:
    if metadata.get("target_probe") is True:
        return False
    if service_type not in _CONTROL_PLANE_SERVICE_TYPES:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname or ""
    return host in _CONTROL_PLANE_HEALTH_HOSTS or host.endswith(".spectra.local")


def _result(
    status: str,
    *,
    latency_ms: float | None = None,
    critical: bool = True,
    error: str | None = None,
    **extra: Any,
) -> HealthMap:
    item: HealthMap = {"status": status, "critical": critical}
    if latency_ms is not None:
        item["latency_ms"] = latency_ms
    if error:
        item["error"] = error
    item.update({k: v for k, v in extra.items() if v is not None})
    return item


async def probe_http_health(
    url: str,
    *,
    path: str = "/health",
    timeout: float = 5.0,
    critical: bool = True,
    headers: dict[str, str] | None = None,
) -> HealthMap:
    """Probe an HTTP health endpoint and include latency in the result."""
    if not url:
        return _result("not_configured", critical=False)

    try:
        import httpx
    except ImportError:
        return _result("unhealthy", critical=critical, error="httpx unavailable", url=url, path=path)

    target = f"{url.rstrip('/')}{path}"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(target, headers=headers)
        body: Any = None
        try:
            body = response.json()
        except ValueError:
            body = None
        response_status = _status_from_http(response.status_code)
        if isinstance(body, dict) and response.status_code == 200:
            response_status = _normalize_status(body.get("status", response_status))
        return _result(
            response_status,
            latency_ms=_latency_ms(start),
            critical=critical,
            http_status=response.status_code,
            url=url,
            path=path,
            response=body if isinstance(body, dict) else None,
        )
    except Exception as exc:
        return _result(
            "unhealthy",
            latency_ms=_latency_ms(start),
            critical=critical,
            error=type(exc).__name__,
            url=url,
            path=path,
        )


async def _check_database(db: AsyncSession) -> HealthMap:
    start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        return _result("healthy", latency_ms=_latency_ms(start))
    except (OSError, SQLAlchemyError, Exception) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_redis() -> HealthMap:
    global _redis_client
    settings = get_settings()
    redis_url = settings.RATE_LIMIT_STORAGE
    if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
        return _result("not_configured", critical=False)

    start = time.monotonic()
    try:
        import redis.asyncio as aioredis

        if _redis_client is None:
            _redis_client = aioredis.from_url(redis_url, socket_timeout=2)
        await _redis_client.ping()
        return _result("healthy", latency_ms=_latency_ms(start))
    except Exception as exc:
        _redis_client = None
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_storage() -> HealthMap:
    start = time.monotonic()
    try:
        from spectra_storage_policy.storage import get_storage_service

        storage = get_storage_service()
        storage_health = await storage.health_check()
        raw_status = storage_health.get("status", "unknown")
        status = _normalize_status(raw_status)
        return _result(
            status,
            latency_ms=_latency_ms(start),
            error=storage_health.get("error"),
            details=storage_health,
        )
    except Exception as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_llm() -> HealthMap:
    start = time.monotonic()
    try:
        from spectra_ai_core.gateway.ai_gateway import get_ai_gateway

        llm = await get_ai_gateway().check_llm_status()
        available = bool(llm.get("available"))
        return _result(
            "healthy" if available else "unhealthy",
            latency_ms=_latency_ms(start),
            provider=llm.get("provider"),
            message=llm.get("status"),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_embeddings() -> HealthMap:
    start = time.monotonic()
    try:
        from spectra_ai_core.gateway.ai_gateway import get_ai_gateway

        emb = await get_ai_gateway().check_embeddings_status()
        if emb.get("functional"):
            status = "healthy"
        elif emb.get("status") == "fallback":
            status = "degraded"
        else:
            status = _normalize_status(emb.get("status"))
        return _result(status, latency_ms=_latency_ms(start), details=emb)
    except (OSError, RuntimeError, ValueError) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_cache() -> HealthMap:
    start = time.monotonic()
    try:
        from spectra_infra.cache import get_cache

        cache = get_cache()
        if not cache:
            return _result("unhealthy", latency_ms=_latency_ms(start), error="Cache not initialized")
        stats = cache.get_stats()
        return _result("healthy", latency_ms=_latency_ms(start), hit_rate_percent=stats.get("hit_rate_percent", 0))
    except (OSError, ConnectionError, TimeoutError) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_sandbox_pool() -> HealthMap:
    start = time.monotonic()
    try:
        from spectra_tools.sandbox import get_sandbox_pool

        pool = get_sandbox_pool()
        if pool and pool.available:
            return _result("healthy", latency_ms=_latency_ms(start))
        if pool:
            return _result("unhealthy", latency_ms=_latency_ms(start), error="Docker not accessible")
        return _result("not_configured", latency_ms=_latency_ms(start), critical=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), error=type(exc).__name__)


async def _check_disk() -> HealthMap:
    start = time.monotonic()
    try:
        usage = shutil.disk_usage("/app/data")
        free_gb = round(usage.free / (1024**3), 2)
        total_gb = round(usage.total / (1024**3), 2)
        used_pct = round(usage.used / usage.total * 100, 1)
        return _result(
            "healthy" if used_pct < 90 else "degraded",
            latency_ms=_latency_ms(start),
            critical=False,
            free_gb=free_gb,
            total_gb=total_gb,
            used_percent=used_pct,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _result("unhealthy", latency_ms=_latency_ms(start), critical=False, error=type(exc).__name__)


def _configured_services() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    return {
        "api": {"url": "", "path": "/api/health", "critical": True},
        "ai_service": {"url": settings.AI_SERVICE_URL, "path": "/health", "critical": True},
        "tensorzero": {
            "url": getattr(settings, "TENSORZERO_GATEWAY_URL", ""),
            "path": "/health",
            "critical": True,
        },
        "scheduler": {"url": settings.SCHEDULER_SERVICE_URL, "path": "/health", "critical": True},
        "worker": {"url": settings.WORKER_SERVICE_URL, "path": "/health", "critical": True},
    }


async def _collect_services(include_api: bool = True) -> dict[str, HealthMap]:
    services: dict[str, HealthMap] = {}
    probes = []
    names = []
    for name, cfg in _configured_services().items():
        if name == "api":
            if include_api:
                services[name] = _result("healthy", critical=True, instance=os.environ.get("HOSTNAME", "unknown"))
            continue
        names.append(name)
        probes.append(
            probe_http_health(
                cfg["url"],
                path=cfg["path"],
                critical=cfg.get("critical", True),
                timeout=5.0,
            )
        )
    for name, result in zip(names, await asyncio.gather(*probes), strict=False):
        services[name] = result
    return services


async def _collect_nodes(db: AsyncSession, *, live_probe: bool) -> dict[str, list[HealthMap]]:
    try:
        from spectra_persistence.models.server_node import ServerNode
    except ImportError:
        return {}

    rows = (await db.execute(select(ServerNode).where(ServerNode.is_active))).scalars().all()
    if not rows:
        return {}

    grouped: dict[str, list[HealthMap]] = {}
    probes = []
    nodes = []
    for row in rows:
        node = row.to_dict()
        nodes.append(node)
        if live_probe:
            raw_metadata = node.get("metadata")
            metadata: dict[str, Any] = (
                {str(key): value for key, value in raw_metadata.items()}
                if isinstance(raw_metadata, dict)
                else {}
            )
            path_value = metadata.get("health_path")
            path = path_value if isinstance(path_value, str) and path_value else "/health"
            if _is_control_plane_health_url(str(node.get("url", "")), str(node.get("service_type", "")), metadata):
                probes.append(probe_http_health(node["url"], path=path, timeout=5.0, critical=False))
            else:
                probes.append(asyncio.sleep(0, result=_result("not_configured", critical=False, error="live_probe_not_allowed")))
        else:
            probes.append(asyncio.sleep(0, result=None))

    probe_results = await asyncio.gather(*probes)
    for node, live in zip(nodes, probe_results, strict=False):
        service_type = node.get("service_type", "unknown")
        metadata = dict(node.get("metadata")) if isinstance(node.get("metadata"), dict) else {}
        item: HealthMap = {
            "id": node.get("id"),
            "name": node.get("name"),
            "service_type": service_type,
            "url": node.get("url"),
            "status": _normalize_status(node.get("health_status")),
            "last_error": node.get("last_error"),
            "last_health_check": node.get("last_health_check"),
            "weight": node.get("weight"),
            "current_load": node.get("current_load"),
            "max_capacity": node.get("max_capacity"),
            "metrics": metadata.get("node_metrics"),
        }
        if live:
            item["live_probe"] = live
            if live.get("error") != "live_probe_not_allowed":
                item["status"] = live.get("status", item["status"])
            if live.get("latency_ms") is not None:
                item["latency_ms"] = live["latency_ms"]
        grouped.setdefault(service_type, []).append(item)
    return grouped


def _overall_status(groups: Iterable[dict[str, HealthMap] | HealthMap]) -> str:
    saw_degraded = False
    for group in groups:
        values = group.values() if isinstance(group, dict) else [group]
        for item in values:
            if not item.get("critical", True):
                continue
            status = _normalize_status(item.get("status"))
            if status == "unhealthy":
                return "degraded"
            if status == "degraded":
                saw_degraded = True
    return "degraded" if saw_degraded else "healthy"


def _summary(components: dict[str, HealthMap], services: dict[str, HealthMap], nodes: dict[str, list[HealthMap]]) -> dict:
    total_nodes = sum(len(items) for items in nodes.values())
    healthy_nodes = sum(1 for items in nodes.values() for item in items if _normalize_status(item.get("status")) == "healthy")
    return {
        "components": {
            "total": len(components),
            "healthy": sum(1 for item in components.values() if _normalize_status(item.get("status")) == "healthy"),
        },
        "services": {
            "total": len(services),
            "healthy": sum(1 for item in services.values() if _normalize_status(item.get("status")) == "healthy"),
        },
        "nodes": {"total": total_nodes, "healthy": healthy_nodes},
    }


async def collect_platform_health(
    db: AsyncSession,
    *,
    detail: str = "basic",
    scope: str = "platform",
    include: str | None = None,
    service: str | None = None,
) -> HealthMap:
    """Return canonical platform health.

    ``basic`` is safe for anonymous probes. ``full`` is intended for admins or
    trusted internal callers and includes detailed service/node diagnostics.
    """
    detail = (detail or "basic").lower()
    scope = (scope or "platform").lower()
    include_tokens = {part.strip() for part in (include or "").split(",") if part.strip()}
    cache_key = f"{detail}:{scope}:{include or ''}:{service or ''}"
    now = time.monotonic()
    cached = _health_cache.get(cache_key)
    if cached is not None:
        cached_at, cached_result = cached
        if now - cached_at < _HEALTH_CACHE_TTL_SECONDS:
            return cached_result

    full = detail in {"full", "verbose", "detailed"}
    include_services = full or scope in {"platform", "services", "public", "ready"} or "services" in include_tokens
    include_nodes = (full and scope != "ready") or scope == "nodes" or "nodes" in include_tokens

    components = {
        "database": await _check_database(db),
        "redis": await _check_redis(),
    }
    if full or scope == "public" or "storage" in include_tokens or "s3" in include_tokens:
        components["s3"] = await _check_storage()

    if full:
        extra_checks = await asyncio.gather(
            _check_llm(),
            _check_embeddings(),
            _check_cache(),
            _check_sandbox_pool(),
            _check_disk(),
        )
        components.update(
            {
                "llm": extra_checks[0],
                "embeddings": extra_checks[1],
                "cache": extra_checks[2],
                "sandbox_pool": extra_checks[3],
                "disk": extra_checks[4],
            }
        )

    services = await _collect_services() if include_services else {}
    if service and service in services:
        services = {service: services[service]}
    nodes = await _collect_nodes(db, live_probe=full) if include_nodes else {}

    groups: list[dict[str, HealthMap] | HealthMap] = [components]
    if scope in {"platform", "services", "public", "ready"} or full:
        groups.append(services)
    status = _overall_status(groups)

    result: HealthMap = {
        "status": status,
        "service": "spectra",
        "version": __version__,
        "detail": "full" if full else "basic",
        "scope": scope,
        "timestamp": _now(),
        "instance": os.environ.get("HOSTNAME", "unknown"),
        "components": components,
        "services": services,
        "nodes": nodes,
        "summary": _summary(components, services, nodes),
    }
    _health_cache[cache_key] = (now, result)
    return result


def readiness_from_health(health: HealthMap) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for name, item in health.get("components", {}).items():
        checks[name] = _normalize_status(item.get("status")) == "healthy" or item.get("status") == "not_configured"
    for name, item in health.get("services", {}).items():
        checks[name] = _normalize_status(item.get("status")) == "healthy"
    return checks
