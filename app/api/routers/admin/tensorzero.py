"""TensorZero gateway admin proxy — admin-only endpoints."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

import aiofiles

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 test runner
    tomllib = None

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.constants import API_DEFAULT_PAGE_SIZE, API_MAX_PAGE_SIZE
from app.core.rbac import Permission, require_permission
from app.models.user import User

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "tensorzero.toml"

router = APIRouter()

_TOML_SAFE_VALUE_RE = re.compile(r"^[a-zA-Z0-9._/:+-]+$")


def _validate_toml_value(value: str, field_name: str) -> str:
    if not value:
        return ""
    if not _TOML_SAFE_VALUE_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {field_name}: model names may only contain letters, digits, dot, underscore, slash, and hyphen"
        )
    return value


def _tz_url() -> str:
    url = settings.TENSORZERO_GATEWAY_URL
    if not url:
        return ""
    return url.rstrip("/")


@router.get("/api/v1/admin/tensorzero/status")
async def tz_status(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Get TensorZero gateway status and config summary."""
    base = _tz_url()
    if not base:
        return JSONResponse({"online": False, "error": "Gateway URL not configured"}, status_code=503)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(f"{base}/health")
            health.raise_for_status()

            status_data = {}
            try:
                status_resp = await client.get(f"{base}/status")
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
            except (httpx.HTTPError, ValueError):
                pass

        dashboard_url = settings.PLATFORM_BASE_URL.rstrip("/") + "/dashboard" if settings.PLATFORM_BASE_URL else None

        return {
            "online": True,
            "gateway_url": base,
            "functions_count": len(status_data.get("functions", {})),
            "models_count": len(status_data.get("models", {})),
            "metrics_count": len(status_data.get("metrics", {})),
            "dashboard_url": dashboard_url,
        }

    except (httpx.HTTPError, OSError) as e:
        logger.warning("TensorZero health check failed: %s", e)
        return JSONResponse({"online": False, "error": "TensorZero gateway unavailable"}, status_code=503)


@router.get("/api/v1/admin/tensorzero/inferences")
async def tz_inferences(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    limit: int = Query(API_DEFAULT_PAGE_SIZE, ge=1, le=API_MAX_PAGE_SIZE),
):
    """Get recent inferences from TensorZero."""
    base = _tz_url()
    if not base:
        return {"inferences": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/inferences", params={"limit": limit})
            if resp.status_code == 200:
                return resp.json()
    except (httpx.HTTPError, OSError) as e:
        logger.warning("Failed to fetch TZ inferences: %s", e)

    return {"inferences": []}


@router.get("/api/v1/admin/tensorzero/functions")
async def tz_functions(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Get function config summary from TensorZero."""
    base = _tz_url()
    if not base:
        return {"functions": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/status")
            if resp.status_code == 200:
                data = resp.json()
                functions = []
                for name, config in data.get("functions", {}).items():
                    functions.append(
                        {
                            "name": name,
                            "type": config.get("type", "chat"),
                            "variant_count": len(config.get("variants", {})),
                        }
                    )
                return {"functions": functions}
    except (httpx.HTTPError, OSError) as e:
        logger.warning("Failed to fetch TZ functions: %s", e)

    return {"functions": []}


@router.get("/api/v1/admin/tensorzero/config")
async def tz_config(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Read current TensorZero model configuration from tensorzero.toml."""
    if not _CONFIG_PATH.exists():
        return {"models": {}, "provider_type": "openai"}
    if tomllib is None:
        return JSONResponse({"detail": "TOML parsing support is unavailable"}, status_code=503)
    async with aiofiles.open(_CONFIG_PATH, "rb") as f:
        raw = await f.read()
    config = tomllib.loads(raw.decode())
    models = {}
    provider_type = "openai"
    for tier in ("fast", "balanced", "capable"):
        tier_conf = config.get("models", {}).get(tier, {})
        providers = tier_conf.get("providers", {})
        primary = providers.get("primary", {})
        fallback = providers.get("fallback", {})
        models[tier] = {
            "primary": primary.get("model_name", ""),
            "fallback": fallback.get("model_name", ""),
        }
        if primary.get("type"):
            provider_type = primary["type"]
    return {"models": models, "provider_type": provider_type}


@router.put("/api/v1/admin/tensorzero/config")
async def tz_update_config(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update TensorZero model config by rewriting tensorzero.toml."""
    body = await request.json()
    models = body.get("models", {})
    try:
        provider_type = _validate_toml_value(str(body.get("provider_type", "openai")), "provider_type")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Read current to preserve functions/metrics
    current: dict = {}
    if _CONFIG_PATH.exists():
        if tomllib is None:
            raise HTTPException(status_code=503, detail="TOML parsing support is unavailable")
        async with aiofiles.open(_CONFIG_PATH, "rb") as f:
            raw = await f.read()
        current = tomllib.loads(raw.decode())

    # Normalize model values: accept either string or {primary, fallback} dict
    tiers: dict[str, dict[str, str]] = {}
    try:
        for tier in ("fast", "balanced", "capable"):
            raw = models.get(tier, "")
            if isinstance(raw, dict):
                tiers[tier] = {
                    "primary": _validate_toml_value(str(raw.get("primary", "")), f"{tier}.primary"),
                    "fallback": _validate_toml_value(str(raw.get("fallback", "")), f"{tier}.fallback"),
                }
            else:
                tiers[tier] = {"primary": _validate_toml_value(str(raw), f"{tier}.primary"), "fallback": ""}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    toml_lines = [
        "# TensorZero Gateway Configuration for Spectra",
        "# Auto-generated by admin UI. Manual edits will be preserved on next save.",
        "",
        "[gateway]",
        'bind_address = "0.0.0.0:3000"',
        "",
        "# --- Models ---",
    ]

    for tier_name, tier_models in tiers.items():
        primary = tier_models["primary"]
        fallback = tier_models["fallback"]
        if fallback:
            toml_lines += [
                f"[models.{tier_name}]",
                'routing = ["primary", "fallback"]',
                "",
                f"[models.{tier_name}.providers.primary]",
                f'type = "{provider_type}"',
                f'model_name = "{primary}"',
                "",
                f"[models.{tier_name}.providers.fallback]",
                f'type = "{provider_type}"',
                f'model_name = "{fallback}"',
                "",
            ]
        else:
            toml_lines += [
                f"[models.{tier_name}]",
                'routing = ["primary"]',
                "",
                f"[models.{tier_name}.providers.primary]",
                f'type = "{provider_type}"',
                f'model_name = "{primary}"',
                "",
            ]

    toml_lines.append("# --- Functions ---")
    for fname, fconf in current.get("functions", {}).items():
        ftype = fconf.get("type", "chat")
        toml_lines += [f"[functions.{fname}]", f'type = "{ftype}"', ""]
        for vname, vconf in fconf.get("variants", {}).items():
            vtype = vconf.get("type", "chat_completion")
            vmodel = vconf.get("model", "balanced")
            toml_lines += [
                f"[functions.{fname}.variants.{vname}]",
                f'type = "{vtype}"',
                f'model = "{vmodel}"',
                "",
            ]

    toml_lines.append("# --- Metrics ---")
    for mname, mconf in current.get("metrics", {}).items():
        mtype = mconf.get("type", "boolean")
        mlevel = mconf.get("level", "inference")
        mopt = mconf.get("optimize", "max")
        toml_lines += [
            f"[metrics.{mname}]",
            f'type = "{mtype}"',
            f'level = "{mlevel}"',
            f'optimize = "{mopt}"',
            "",
        ]

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(toml_lines) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=_CONFIG_PATH.parent, delete=False) as tmp_file:
        tmp_file.write(rendered)
        temp_path = tmp_file.name
    os.replace(temp_path, _CONFIG_PATH)

    return {
        "status": "ok",
        "message": "Config updated. Restart TensorZero container to apply changes.",
    }


@router.get("/api/v1/admin/tensorzero/analytics")
async def tz_analytics(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    hours: int = Query(24, ge=1, le=168),
):
    """Get inference analytics from TensorZero."""
    base = _tz_url()
    if not base:
        return {"analytics": {}, "available": False}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base}/status")
            if resp.status_code != 200:
                return {"analytics": {}, "available": False}

            status = resp.json()
            functions = status.get("functions", {})
            models = status.get("models", {})

            return {
                "available": True,
                "functions_count": len(functions),
                "models_count": len(models),
                "functions": {
                    name: {
                        "type": conf.get("type", "chat"),
                        "variants": list(conf.get("variants", {}).keys()),
                    }
                    for name, conf in functions.items()
                },
                "models": {
                    name: {
                        "providers": list(conf.get("providers", {}).keys()),
                    }
                    for name, conf in models.items()
                },
            }
    except (httpx.HTTPError, OSError) as e:
        logger.warning("TensorZero analytics fetch failed: %s", e)
        return {"analytics": {}, "available": False, "error": "Analytics unavailable"}


@router.get("/api/v1/admin/tensorzero/model-performance")
async def tz_model_performance(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Get model performance metrics from cost trackers."""
    from app.services.ai.cost_tracker import get_cost_trackers

    cost_trackers = get_cost_trackers()
    performance = {}
    for name, tracker in (cost_trackers or {}).items():
        summary = tracker.get_summary()
        performance[name] = {
            "total_calls": summary["total_calls"],
            "total_tokens": summary["total_tokens"],
            "total_cost_usd": summary["total_cost_usd"],
            "avg_tokens_per_call": round(summary["total_tokens"] / max(summary["total_calls"], 1), 1),
        }
    return {"models": performance}
