"""TensorZero gateway admin proxy — admin-only endpoints."""

from __future__ import annotations

import json
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

from spectra_api.authz import Permission, require_permission
from spectra_common.config import settings
from spectra_common.constants import API_DEFAULT_PAGE_SIZE, API_MAX_PAGE_SIZE
from spectra_persistence.models.user import User

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "tensorzero.toml"

router = APIRouter()

_TOML_SAFE_VALUE_RE = re.compile(r"^[a-zA-Z0-9._/:+-]+$")

# DeepSeek-only platform: the legacy deepseek-chat/deepseek-reasoner aliases are deprecated
# (2026-07-24) and both alias to v4-flash, so only the explicit V4 IDs are accepted.
_ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


def _validate_toml_value(value: str, field_name: str) -> str:
    if not value:
        return ""
    if not _TOML_SAFE_VALUE_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {field_name}: model names may only contain letters, digits, dot, underscore, slash, and hyphen"
        )
    return value


def _toml_inline(value: object) -> str:
    """Render a parsed TOML value (str / list / dict of scalars) back to inline TOML.

    Only used to round-trip provider ``extra_body`` (a list of {pointer, value} tables),
    so it covers strings, numbers, bools, lists, and string-keyed tables — enough to
    preserve thinking config without a full TOML serializer dependency.
    """
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_inline(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_inline(v)}" for k, v in value.items()) + " }"
    return json.dumps(str(value))


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


def _thinking_mode(primary: dict) -> str:
    """Extract the DeepSeek thinking mode from a provider's extra_body, if any."""
    for entry in primary.get("extra_body", []) or []:
        if isinstance(entry, dict) and entry.get("pointer") == "/thinking/type":
            return str(entry.get("value", ""))
    return ""


@router.get("/api/v1/admin/tensorzero/config")
async def tz_config(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Read the current per-tier DeepSeek model + thinking mode from tensorzero.toml."""
    allowed = sorted(_ALLOWED_MODELS)
    if not _CONFIG_PATH.exists():
        return {"models": {}, "provider_type": "deepseek", "allowed_models": allowed}
    if tomllib is None:
        return JSONResponse({"detail": "TOML parsing support is unavailable"}, status_code=503)
    async with aiofiles.open(_CONFIG_PATH, "rb") as f:
        raw = await f.read()
    config = tomllib.loads(raw.decode())
    models = {}
    provider_type = "deepseek"
    for tier in ("fast", "balanced", "capable"):
        tier_conf = config.get("models", {}).get(tier, {})
        primary = tier_conf.get("providers", {}).get("primary", {})
        models[tier] = {
            "model": primary.get("model_name", ""),
            "thinking": _thinking_mode(primary),
        }
        if primary.get("type"):
            provider_type = primary["type"]
    return {"models": models, "provider_type": provider_type, "allowed_models": allowed}


@router.put("/api/v1/admin/tensorzero/config")
async def tz_update_config(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update the DeepSeek model behind each tier by rewriting tensorzero.toml.

    Only the per-tier ``model_name`` is editable; every other provider field (the
    DeepSeek ``type``, ``api_key_location``, and the thinking ``extra_body``) is preserved
    verbatim, so an admin model swap can never strip a tier's thinking configuration.
    """
    if tomllib is None:
        raise HTTPException(status_code=503, detail="TOML parsing support is unavailable")
    body = await request.json()
    models = body.get("models", {})

    # Read current config to preserve provider details, functions, and metrics.
    current: dict = {}
    if _CONFIG_PATH.exists():
        async with aiofiles.open(_CONFIG_PATH, "rb") as f:
            raw = await f.read()
        current = tomllib.loads(raw.decode())

    # Each tier maps to exactly one DeepSeek model. Accept a bare string or {"primary": ...}.
    requested: dict[str, str] = {}
    try:
        for tier in ("fast", "balanced", "capable"):
            raw = models.get(tier, "")
            value = raw.get("primary", "") if isinstance(raw, dict) else raw
            requested[tier] = _validate_toml_value(str(value), f"{tier}.model_name")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Validation error: {str(exc)[:200]}") from exc

    # DeepSeek-only platform: reject anything but the two non-deprecated V4 model IDs.
    for tier, model_name in requested.items():
        if model_name and model_name not in _ALLOWED_MODELS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid model for tier '{tier}': {model_name!r}. Allowed: {sorted(_ALLOWED_MODELS)}",
            )

    toml_lines = [
        "# TensorZero Gateway Configuration for Spectra",
        "# Models edited via the admin panel; functions/metrics preserved from the prior config.",
        "",
        "[gateway]",
        'bind_address = "0.0.0.0:3000"',
        "",
        "# --- Models ---",
    ]

    current_models = current.get("models", {})
    for tier_name in ("fast", "balanced", "capable"):
        current_tier = current_models.get(tier_name, {})
        current_primary = current_tier.get("providers", {}).get("primary", {})
        model_name = requested.get(tier_name) or current_primary.get("model_name", "")
        # Preserve every provider field except model_name (type, api_key_location, extra_body).
        preserved = {k: v for k, v in current_primary.items() if k != "model_name"}
        provider_type = preserved.pop("type", "deepseek")
        extra_body = preserved.pop("extra_body", None)
        toml_lines += [
            f"[models.{tier_name}]",
            'routing = ["primary"]',
            "",
            f"[models.{tier_name}.providers.primary]",
            f'type = "{provider_type}"',
            f'model_name = "{model_name}"',
            *[f'{k} = "{v}"' for k, v in preserved.items()],
        ]
        if extra_body is not None:
            toml_lines.append(f"extra_body = {_toml_inline(extra_body)}")
        toml_lines.append("")

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

    # Apply by rolling the gateway so it reloads the rewritten config. In Swarm the config
    # is delivered to the gateway via the shared deploy mechanism; restart_service performs a
    # rolling, zero-state-loss force update. No-ops cleanly when not a Swarm manager.
    applied = False
    try:
        from spectra_scaling import docker_client

        applied = await docker_client.restart_service("spectra_tensorzero")
    except Exception:
        # Apply is best-effort; the config write already succeeded.
        logger.warning("Could not auto-restart TensorZero after config update", exc_info=True)

    return {
        "status": "ok",
        "applied": applied,
        "message": (
            "Models updated and gateway restarted."
            if applied
            else "Models updated. Restart the TensorZero gateway to apply."
        ),
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
    from spectra_ai_core.cost_tracker import get_cost_trackers

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
