"""TensorZero gateway admin proxy — admin-only endpoints."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.constants import API_DEFAULT_PAGE_SIZE, API_MAX_PAGE_SIZE
from app.core.rbac import Permission, require_permission
from app.models.user import User

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "tensorzero.toml"

router = APIRouter()


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
        return JSONResponse({"online": False, "error": str(e)}, status_code=503)


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
                    functions.append({
                        "name": name,
                        "type": config.get("type", "chat"),
                        "variant_count": len(config.get("variants", {})),
                    })
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
    with open(_CONFIG_PATH, "rb") as f:
        config = tomllib.load(f)
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
    provider_type = body.get("provider_type", "openai")

    # Read current to preserve functions/metrics
    current: dict = {}
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "rb") as f:
            current = tomllib.load(f)

    # Normalize model values: accept either string or {primary, fallback} dict
    tiers: dict[str, dict[str, str]] = {}
    for tier in ("fast", "balanced", "capable"):
        raw = models.get(tier, "")
        if isinstance(raw, dict):
            tiers[tier] = {
                "primary": raw.get("primary", ""),
                "fallback": raw.get("fallback", ""),
            }
        else:
            tiers[tier] = {"primary": raw, "fallback": ""}

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
    _CONFIG_PATH.write_text("\n".join(toml_lines) + "\n")

    return {
        "status": "ok",
        "message": "Config updated. Restart TensorZero container to apply changes.",
    }
