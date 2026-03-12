"""DB-backed runtime settings hydration and normalization."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.config import SystemConfig

logger = logging.getLogger("spectra.services.system.runtime_settings")

NEW_AI_CONFIG_KEYS = (
    "AI_PROVIDER_PROFILES",
    "AI_PROVIDER_ROUTING",
    "AI_PROVIDER_FALLBACKS",
)
LEGACY_AI_CONFIG_KEYS = (
    "AI_PROVIDER",
    "LLM_MODEL",
    "LLM_TIER1_MODEL",
    "LLM_TIER2_MODEL",
    "LLM_TIER3_MODEL",
    "OLLAMA_ENABLED",
    "LLM_API_BASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "LLM_API_KEY",
)
GENERAL_RUNTIME_FIELD_MAP: dict[str, tuple[str, str]] = {
    # S3/MinIO Object Storage
    "S3_ENDPOINT_URL": ("S3_ENDPOINT_URL", "str"),
    "S3_ACCESS_KEY": ("S3_ACCESS_KEY", "secret"),
    "S3_SECRET_KEY": ("S3_SECRET_KEY", "secret"),
    "S3_REGION": ("S3_REGION", "str"),
    "LOG_LEVEL": ("LOG_LEVEL", "str"),
    "PLUGIN_SAFE_MODE": ("PLUGIN_SAFE_MODE", "bool"),
    "CONNECT_BACK_HOST": ("CONNECT_BACK_HOST", "str"),
    "REQUIRE_APPROVAL": ("REQUIRE_APPROVAL", "bool"),
    "FULLY_AUTOMATED": ("FULLY_AUTOMATED", "bool"),
    "NOTIFICATION_WEBHOOK": ("NOTIFICATION_WEBHOOK", "nullable_str"),
    "EMBEDDING_MODEL": ("EMBEDDING_MODEL", "str"),
    "PLATFORM_DOMAIN": ("PLATFORM_DOMAIN", "str"),
    "PLATFORM_BASE_URL": ("PLATFORM_BASE_URL", "str"),
    "PLATFORM_EXPOSED": ("PLATFORM_EXPOSED", "bool"),
    "SANDBOX_MAX_CONTAINERS": ("SANDBOX_MAX_CONTAINERS", "int"),
    "SANDBOX_MEMORY_LIMIT": ("SANDBOX_MEMORY_LIMIT", "str"),
    "SANDBOX_CPU_SHARES": ("SANDBOX_CPU_SHARES", "int"),
    "SANDBOX_MAX_LIFETIME": ("SANDBOX_MAX_LIFETIME", "int"),
    "SANDBOX_RESOURCE_TIERS": ("SANDBOX_RESOURCE_TIERS", "str"),
    "SANDBOX_NETWORK_ISOLATION": ("SANDBOX_NETWORK_ISOLATION", "bool"),
    "SANDBOX_IDLE_TIMEOUT": ("SANDBOX_IDLE_TIMEOUT", "int"),
    "SANDBOX_HEARTBEAT_INTERVAL": ("SANDBOX_HEARTBEAT_INTERVAL", "int"),
    "SANDBOX_PER_USER_LIMIT": ("SANDBOX_PER_USER_LIMIT", "int"),
    "SANDBOX_DEFAULT_PRIORITY": ("SANDBOX_DEFAULT_PRIORITY", "int"),
    "SANDBOX_OOM_ESCALATION_ENABLED": ("SANDBOX_OOM_ESCALATION_ENABLED", "bool"),
    "SANDBOX_WARM_POOL_ENABLED": ("SANDBOX_WARM_POOL_ENABLED", "bool"),
    "SANDBOX_WARM_POOL_SIZE": ("SANDBOX_WARM_POOL_SIZE", "int"),
    "SANDBOX_AUTO_BUILD_IMAGE": ("SANDBOX_AUTO_BUILD_IMAGE", "bool"),
    "SANDBOX_IMAGE_SCAN_ENABLED": ("SANDBOX_IMAGE_SCAN_ENABLED", "bool"),
    "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": ("SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool"),
    # External Service Endpoints
    # LLM gateway fields removed
    "SANDBOX_ORCHESTRATOR_URL": ("SANDBOX_ORCHESTRATOR_URL", "nullable_str"),
    "SANDBOX_ORCHESTRATOR_TIMEOUT": ("SANDBOX_ORCHESTRATOR_TIMEOUT", "int"),
}
_LITELLM_PROVIDER_PREFIXES = {
    "anthropic",
    "azure",
    "bedrock",
    "cohere",
    "gemini",
    "groq",
    "mistral",
    "ollama",
    "openai",
    "openrouter",
    "vertex_ai",
}
_CLOUD_PROVIDER_ALIASES = {"api", "openai", "litellm", "ollama", "qwen", "z.ai", "anthropic", "groq"}


@dataclass(slots=True)
class RuntimeAIConfig:
    profiles: dict[str, dict[str, Any]]
    routing: dict[str, str]
    fallbacks: dict[str, list[str]]


def _as_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _load_json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON runtime config value ignored")
        return {}
    return data if isinstance(data, dict) else {}


def _get_secret_value(secret: Any) -> str:
    if secret is None:
        return ""
    getter = getattr(secret, "get_secret_value", None)
    if callable(getter):
        return str(getter() or "")
    return str(secret or "")


def _find_first_profile(profiles: dict[str, dict[str, Any]], providers: tuple[str, ...]) -> dict[str, Any] | None:
    for profile in profiles.values():
        if profile.get("provider") in providers:
            return profile
    return None


def _normalize_provider_name(provider: Any) -> str:
    normalized = str(provider or "mock").strip().lower() or "mock"
    if normalized in _CLOUD_PROVIDER_ALIASES:
        return "litellm"
    return normalized


def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    raw_provider = str(profile.get("provider", "mock")).strip().lower()
    model = str(profile.get("model", "")).strip()
    if raw_provider == "ollama" and not model.startswith("ollama/"):
        model = f"ollama/{model}"
    normalized = {
        "provider": _normalize_provider_name(raw_provider),
        "model": model,
    }
    base_url = profile.get("base_url")
    if base_url:
        normalized["base_url"] = str(base_url).strip()
    api_key = profile.get("api_key")
    if api_key:
        normalized["api_key"] = str(api_key)
    return normalized


def _serialize_tier_model(
    profile_name: str,
    routing: dict[str, str],
    profiles: dict[str, dict[str, Any]],
) -> str:
    target_name = routing.get(profile_name)
    if not target_name:
        return ""
    profile = profiles.get(target_name)
    if not profile:
        return ""

    model = str(profile.get("model", "")).strip()
    if not model:
        return ""

    return model


def _infer_profile_from_model(
    model_name: str,
    default_provider: str,
    rows: dict[str, str],
) -> dict[str, Any]:
    profile: dict[str, Any] = {}
    raw_model = (model_name or "").strip()
    if "/" in raw_model:
        prefix, suffix = raw_model.split("/", 1)
        prefix = prefix.strip().lower()
        if prefix == "ollama":
            profile = {
                "provider": "ollama",
                "model": suffix.strip(),
                "base_url": rows.get("OLLAMA_HOST") or settings.OLLAMA_HOST,
            }
        elif prefix == "openai" or prefix in _LITELLM_PROVIDER_PREFIXES:
            profile = {
                "provider": "litellm",
                "model": raw_model,
            }

    if not profile:
        raw_default = str(default_provider or "mock").strip().lower()
        profile = {"provider": default_provider, "model": raw_model}
        if raw_default == "ollama":
            profile["base_url"] = rows.get("OLLAMA_HOST") or settings.OLLAMA_HOST

    if profile.get("provider") not in ("ollama",):
        base_url = rows.get("LLM_API_BASE_URL")
        if base_url:
            profile["base_url"] = base_url
        api_key = rows.get("LLM_API_KEY")
        if api_key:
            profile["api_key"] = api_key

    return _normalize_profile(profile)


def _build_legacy_profiles(rows: dict[str, str]) -> RuntimeAIConfig:
    raw_provider_str = str(rows.get("AI_PROVIDER") or settings.AI_PROVIDER or "mock").strip().lower()
    provider = _normalize_provider_name(raw_provider_str)
    routing: dict[str, str] = {"default": "default"}
    profiles: dict[str, dict[str, Any]] = {}
    fallbacks: dict[str, list[str]] = {}

    default_profile: dict[str, Any]
    if raw_provider_str == "ollama":
        default_profile = {
            "provider": "ollama",
            "model": rows.get("OLLAMA_MODEL") or settings.OLLAMA_MODEL,
            "base_url": rows.get("OLLAMA_HOST") or settings.OLLAMA_HOST,
        }
    elif provider == "litellm":
        default_profile = {
            "provider": "litellm",
            "model": rows.get("LLM_MODEL") or settings.LLM_MODEL,
        }
        base_url = rows.get("LLM_API_BASE_URL") or settings.LLM_API_BASE_URL
        if base_url:
            default_profile["base_url"] = base_url
        api_key = rows.get("LLM_API_KEY") or settings.LLM_API_KEY.get_secret_value()
        if api_key:
            default_profile["api_key"] = api_key
    else:
        default_profile = {
            "provider": "mock",
            "model": rows.get("LLM_MODEL") or settings.LLM_MODEL,
        }

    profiles["default"] = _normalize_profile(default_profile)

    has_api_fallback = bool(rows.get("LLM_API_KEY"))
    if raw_provider_str == "ollama" and has_api_fallback:
        profiles["api-fallback"] = _normalize_profile(
            {
                "provider": "litellm",
                "model": rows.get("LLM_MODEL") or settings.LLM_MODEL,
                "base_url": rows.get("LLM_API_BASE_URL") or settings.LLM_API_BASE_URL,
                "api_key": rows.get("LLM_API_KEY"),
            }
        )
        fallbacks["default"] = ["api-fallback"]
    elif raw_provider_str != "ollama" and provider == "litellm" and _as_bool(rows.get("OLLAMA_ENABLED")):
        profiles["ollama"] = _normalize_profile(
            {
                "provider": "ollama",
                "model": rows.get("OLLAMA_MODEL") or settings.OLLAMA_MODEL,
                "base_url": rows.get("OLLAMA_HOST") or settings.OLLAMA_HOST,
            }
        )
        fallbacks["default"] = ["ollama"]

    for tier_name, row_key in (
        ("tier1", "LLM_TIER1_MODEL"),
        ("tier2", "LLM_TIER2_MODEL"),
        ("tier3", "LLM_TIER3_MODEL"),
    ):
        tier_model = rows.get(row_key, "").strip()
        if not tier_model:
            continue
        profiles[tier_name] = _infer_profile_from_model(
            tier_model,
            default_provider=raw_provider_str,
            rows=rows,
        )
        routing[tier_name] = tier_name

    return RuntimeAIConfig(profiles=profiles, routing=routing, fallbacks=fallbacks)


def normalize_runtime_ai_config(rows: dict[str, str]) -> RuntimeAIConfig:
    """Resolve mixed legacy/new DB rows into one provider-profile runtime shape."""
    legacy = _build_legacy_profiles(rows)
    profiles = dict(legacy.profiles)
    routing = dict(legacy.routing)
    fallbacks = dict(legacy.fallbacks)

    new_profiles = _load_json_dict(rows.get("AI_PROVIDER_PROFILES"))
    for name, profile in new_profiles.items():
        if isinstance(name, str) and isinstance(profile, dict):
            profiles[name] = _normalize_profile(profile)

    new_routing = _load_json_dict(rows.get("AI_PROVIDER_ROUTING"))
    for route_name, profile_name in new_routing.items():
        if isinstance(route_name, str) and isinstance(profile_name, str):
            routing[route_name] = profile_name

    new_fallbacks = _load_json_dict(rows.get("AI_PROVIDER_FALLBACKS"))
    for route_name, fallback_list in new_fallbacks.items():
        if isinstance(route_name, str) and isinstance(fallback_list, list):
            fallbacks[route_name] = [name for name in fallback_list if isinstance(name, str)]

    default_profile_name = routing.get("default", "default")
    if default_profile_name not in profiles:
        default_profile_name = "default"
        routing["default"] = default_profile_name

    for route_name, profile_name in list(routing.items()):
        if profile_name not in profiles:
            routing[route_name] = default_profile_name

    for route_name, fallback_list in list(fallbacks.items()):
        filtered = [name for name in fallback_list if name in profiles]
        if filtered:
            fallbacks[route_name] = filtered
        else:
            fallbacks.pop(route_name, None)

    return RuntimeAIConfig(profiles=profiles, routing=routing, fallbacks=fallbacks)


def runtime_ai_rows_from_settings(settings_obj: Any | None = None) -> dict[str, str]:
    """Create a normalized row-like snapshot from in-memory settings."""
    target_settings = settings_obj or settings
    has_structured_profiles = bool(getattr(target_settings, "AI_PROVIDER_PROFILES", {}) or {})
    return {
        "AI_PROVIDER": str(getattr(target_settings, "AI_PROVIDER", "mock") or "mock"),
        "LLM_MODEL": str(getattr(target_settings, "LLM_MODEL", "") or ""),
        "LLM_TIER1_MODEL": ""
        if has_structured_profiles
        else str(getattr(target_settings, "LLM_TIER1_MODEL", "") or ""),
        "LLM_TIER2_MODEL": ""
        if has_structured_profiles
        else str(getattr(target_settings, "LLM_TIER2_MODEL", "") or ""),
        "LLM_TIER3_MODEL": ""
        if has_structured_profiles
        else str(getattr(target_settings, "LLM_TIER3_MODEL", "") or ""),
        "OLLAMA_ENABLED": "false"
        if has_structured_profiles
        else str(_as_bool(getattr(target_settings, "OLLAMA_ENABLED", False))).lower(),
        "LLM_API_BASE_URL": str(getattr(target_settings, "LLM_API_BASE_URL", "") or ""),
        "OLLAMA_HOST": str(getattr(target_settings, "OLLAMA_HOST", "") or ""),
        "OLLAMA_MODEL": str(getattr(target_settings, "OLLAMA_MODEL", "") or ""),
        "LLM_API_KEY": _get_secret_value(getattr(target_settings, "LLM_API_KEY", "")),
        "AI_PROVIDER_PROFILES": json.dumps(getattr(target_settings, "AI_PROVIDER_PROFILES", {}) or {}, sort_keys=True),
        "AI_PROVIDER_ROUTING": json.dumps(getattr(target_settings, "AI_PROVIDER_ROUTING", {}) or {}, sort_keys=True),
        "AI_PROVIDER_FALLBACKS": json.dumps(
            getattr(target_settings, "AI_PROVIDER_FALLBACKS", {}) or {}, sort_keys=True
        ),
    }


def get_runtime_ai_config_from_settings(settings_obj: Any | None = None) -> RuntimeAIConfig:
    """Resolve runtime AI config from the current in-memory settings singleton."""
    return normalize_runtime_ai_config(runtime_ai_rows_from_settings(settings_obj))


def build_runtime_ai_config_from_payload(
    *,
    provider_profiles: dict[str, dict[str, Any]] | None = None,
    provider_routing: dict[str, str | None] | None = None,
    provider_fallbacks: dict[str, list[str] | None] | None = None,
    base_config: RuntimeAIConfig | None = None,
    legacy_provider: str | None = None,
    legacy_model: str | None = None,
    legacy_api_key: str | None = None,
    legacy_api_base_url: str | None = None,
    legacy_ollama_host: str | None = None,
    legacy_ollama_model: str | None = None,
    legacy_ollama_enabled: bool | None = None,
    legacy_tier_models: dict[str, str | None] | None = None,
) -> RuntimeAIConfig:
    """Build merged runtime AI config from structured or legacy request payloads."""
    has_structured_payload = any(
        value is not None for value in (provider_profiles, provider_routing, provider_fallbacks)
    )
    if not has_structured_payload:
        rows = runtime_ai_rows_from_settings()
        if legacy_provider is not None:
            rows["AI_PROVIDER"] = legacy_provider
        if legacy_model is not None:
            rows["LLM_MODEL"] = legacy_model
        if legacy_api_key is not None:
            rows["LLM_API_KEY"] = legacy_api_key
        if legacy_api_base_url is not None:
            rows["LLM_API_BASE_URL"] = legacy_api_base_url
        if legacy_ollama_host is not None:
            rows["OLLAMA_HOST"] = legacy_ollama_host
        if legacy_ollama_model is not None:
            rows["OLLAMA_MODEL"] = legacy_ollama_model
        if legacy_ollama_enabled is not None:
            rows["OLLAMA_ENABLED"] = str(legacy_ollama_enabled).lower()
        for row_key, value in (legacy_tier_models or {}).items():
            if value is not None:
                rows[row_key] = value
        return normalize_runtime_ai_config(rows)

    resolved_base = base_config or get_runtime_ai_config_from_settings()
    profiles = {name: dict(profile) for name, profile in resolved_base.profiles.items()}
    routing = dict(resolved_base.routing)
    fallbacks = {name: list(chain) for name, chain in resolved_base.fallbacks.items()}

    for name, profile in (provider_profiles or {}).items():
        profiles[name] = _normalize_profile(profile)

    if not profiles:
        return build_runtime_ai_config_from_payload(
            legacy_provider=legacy_provider,
            legacy_model=legacy_model,
            legacy_api_key=legacy_api_key,
            legacy_api_base_url=legacy_api_base_url,
            legacy_ollama_host=legacy_ollama_host,
            legacy_ollama_model=legacy_ollama_model,
            legacy_ollama_enabled=legacy_ollama_enabled,
            legacy_tier_models=legacy_tier_models,
        )

    if not routing:
        routing["default"] = next(iter(profiles))
    for route_name, profile_name in (provider_routing or {}).items():
        if route_name == "default":
            if profile_name:
                routing[route_name] = profile_name
        elif profile_name:
            routing[route_name] = profile_name
        else:
            routing.pop(route_name, None)

    default_profile_name = routing.get("default") or next(iter(profiles))
    if default_profile_name not in profiles:
        default_profile_name = next(iter(profiles))
    routing["default"] = default_profile_name

    for route_name, profile_name in list(routing.items()):
        if profile_name not in profiles:
            if route_name == "default":
                routing[route_name] = default_profile_name
            else:
                routing.pop(route_name, None)

    for route_name, chain in (provider_fallbacks or {}).items():
        filtered_chain = [profile for profile in chain or [] if profile in profiles]
        if filtered_chain:
            fallbacks[route_name] = filtered_chain
        else:
            fallbacks.pop(route_name, None)

    for route_name, chain in list(fallbacks.items()):
        filtered_chain = [profile for profile in chain if profile in profiles]
        if filtered_chain:
            fallbacks[route_name] = filtered_chain
        else:
            fallbacks.pop(route_name, None)

    return RuntimeAIConfig(profiles=profiles, routing=routing, fallbacks=fallbacks)


def serialize_runtime_ai_config_values(
    runtime_ai_config: RuntimeAIConfig,
) -> dict[str, tuple[str, bool]]:
    """Serialize runtime AI config into SystemConfig row values, including compatibility keys."""
    values: dict[str, tuple[str, bool]] = {
        "AI_PROVIDER_PROFILES": (
            json.dumps(runtime_ai_config.profiles, sort_keys=True),
            False,
        ),
        "AI_PROVIDER_ROUTING": (
            json.dumps(runtime_ai_config.routing, sort_keys=True),
            False,
        ),
        "AI_PROVIDER_FALLBACKS": (
            json.dumps(runtime_ai_config.fallbacks, sort_keys=True),
            False,
        ),
    }

    default_profile_name = runtime_ai_config.routing.get("default", "default")
    default_profile = runtime_ai_config.profiles.get(default_profile_name, {})
    values["AI_PROVIDER"] = (str(default_profile.get("provider", "mock")), False)

    cloud_profile = None
    for p in runtime_ai_config.profiles.values():
        if p.get("provider") == "litellm" and not str(p.get("model", "")).startswith("ollama/"):
            cloud_profile = p
            break
    if cloud_profile:
        values["LLM_MODEL"] = (str(cloud_profile.get("model", "")), False)
        values["LLM_API_BASE_URL"] = (str(cloud_profile.get("base_url", "") or ""), False)
        values["LLM_API_KEY"] = (str(cloud_profile.get("api_key", "") or ""), True)

    ollama_profile = None
    for p in runtime_ai_config.profiles.values():
        if str(p.get("model", "")).startswith("ollama/"):
            ollama_profile = p
            break
    if ollama_profile:
        ollama_model = str(ollama_profile.get("model", ""))
        if ollama_model.startswith("ollama/"):
            ollama_model = ollama_model[len("ollama/") :]
        values["OLLAMA_MODEL"] = (ollama_model, False)
        values["OLLAMA_HOST"] = (str(ollama_profile.get("base_url", "") or ""), False)

    values["OLLAMA_ENABLED"] = (
        str(
            any(
                str(profile.get("model", "")).startswith("ollama/")
                for profile_name, profile in runtime_ai_config.profiles.items()
                if profile_name != default_profile_name
            )
        ).lower(),
        False,
    )
    values["LLM_TIER1_MODEL"] = (
        _serialize_tier_model("tier1", runtime_ai_config.routing, runtime_ai_config.profiles),
        False,
    )
    values["LLM_TIER2_MODEL"] = (
        _serialize_tier_model("tier2", runtime_ai_config.routing, runtime_ai_config.profiles),
        False,
    )
    values["LLM_TIER3_MODEL"] = (
        _serialize_tier_model("tier3", runtime_ai_config.routing, runtime_ai_config.profiles),
        False,
    )
    return values


def get_resolved_runtime_ai_config_snapshot(
    runtime_ai_config: RuntimeAIConfig | None = None,
    settings_obj: Any | None = None,
) -> dict[str, Any]:
    """Return a UI-friendly resolved snapshot of the active runtime AI config."""
    config = runtime_ai_config or get_runtime_ai_config_from_settings(settings_obj)
    default_profile_name = config.routing.get("default", "default")
    default_profile = config.profiles.get(default_profile_name, {})

    tiers: dict[str, dict[str, Any]] = {}
    for tier_name in ("tier1", "tier2", "tier3"):
        profile_name = config.routing.get(tier_name, default_profile_name)
        profile = config.profiles.get(profile_name, default_profile)
        tiers[tier_name] = {
            "profile": profile_name,
            "inherits_default": profile_name == default_profile_name,
            "provider": profile.get("provider"),
            "model": profile.get("model"),
            "base_url": profile.get("base_url"),
        }

    return {
        "default_profile": default_profile_name,
        "default_route": {
            "profile": default_profile_name,
            "provider": default_profile.get("provider"),
            "model": default_profile.get("model"),
            "base_url": default_profile.get("base_url"),
        },
        "profiles": config.profiles,
        "routing": config.routing,
        "fallbacks": config.fallbacks,
        "tiers": tiers,
    }


def _apply_general_runtime_settings(rows: dict[str, str]) -> None:
    for key, (attr_name, kind) in GENERAL_RUNTIME_FIELD_MAP.items():
        if key not in rows:
            continue
        value = rows[key]
        if kind == "bool":
            setattr(settings, attr_name, _as_bool(value))
        elif kind == "int":
            try:
                setattr(settings, attr_name, int(value))
            except (ValueError, TypeError):
                pass  # Keep default if DB value is invalid
        elif kind == "nullable_str":
            setattr(settings, attr_name, value or None)
        elif kind == "secret":
            setattr(settings, attr_name, SecretStr(value or ""))
        else:
            setattr(settings, attr_name, value)


def apply_runtime_settings(rows: dict[str, str], runtime_ai_config: RuntimeAIConfig) -> None:
    """Apply DB-backed runtime settings to the in-memory settings singleton."""
    _apply_general_runtime_settings(rows)

    settings.AI_PROVIDER_PROFILES = runtime_ai_config.profiles
    settings.AI_PROVIDER_ROUTING = runtime_ai_config.routing
    settings.AI_PROVIDER_FALLBACKS = runtime_ai_config.fallbacks

    default_profile_name = runtime_ai_config.routing.get("default", "default")
    default_profile = runtime_ai_config.profiles.get(default_profile_name, {})
    default_provider = default_profile.get("provider", "mock")
    settings.AI_PROVIDER = default_provider

    cloud_profile = None
    for p in runtime_ai_config.profiles.values():
        if p.get("provider") == "litellm" and not str(p.get("model", "")).startswith("ollama/"):
            cloud_profile = p
            break
    if cloud_profile:
        settings.LLM_MODEL = str(cloud_profile.get("model", settings.LLM_MODEL))
        settings.LLM_API_BASE_URL = cloud_profile.get("base_url")
        api_key = cloud_profile.get("api_key")
        if api_key:
            settings.LLM_API_KEY = SecretStr(str(api_key))
        else:
            settings.LLM_API_KEY = SecretStr("")
    else:
        settings.LLM_API_BASE_URL = None
        settings.LLM_API_KEY = SecretStr("")

    ollama_profile = None
    for p in runtime_ai_config.profiles.values():
        if str(p.get("model", "")).startswith("ollama/"):
            ollama_profile = p
            break
    if ollama_profile:
        ollama_model = str(ollama_profile.get("model", settings.OLLAMA_MODEL))
        if ollama_model.startswith("ollama/"):
            ollama_model = ollama_model[len("ollama/") :]
        settings.OLLAMA_MODEL = ollama_model
        if ollama_profile.get("base_url"):
            settings.OLLAMA_HOST = str(ollama_profile["base_url"])

    default_model = str(default_profile.get("model", ""))
    if default_provider == "litellm":
        if default_model.startswith("ollama/"):
            settings.OLLAMA_MODEL = default_model[len("ollama/") :]
            if default_profile.get("base_url"):
                settings.OLLAMA_HOST = str(default_profile["base_url"])
        else:
            settings.LLM_MODEL = default_model or settings.LLM_MODEL
            settings.LLM_API_BASE_URL = default_profile.get("base_url")
            api_key = default_profile.get("api_key")
            if api_key:
                settings.LLM_API_KEY = SecretStr(str(api_key))
            else:
                settings.LLM_API_KEY = SecretStr("")

    settings.OLLAMA_ENABLED = any(
        str(profile.get("model", "")).startswith("ollama/")
        for profile_name, profile in runtime_ai_config.profiles.items()
        if profile_name != default_profile_name
    )
    settings.LLM_TIER1_MODEL = _serialize_tier_model("tier1", runtime_ai_config.routing, runtime_ai_config.profiles)
    settings.LLM_TIER2_MODEL = _serialize_tier_model("tier2", runtime_ai_config.routing, runtime_ai_config.profiles)
    settings.LLM_TIER3_MODEL = _serialize_tier_model("tier3", runtime_ai_config.routing, runtime_ai_config.profiles)


async def upsert_system_config_values(
    session: AsyncSession,
    values: dict[str, tuple[str, bool]],
) -> None:
    for key, (value, is_secret) in values.items():
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.is_secret = is_secret
        else:
            session.add(SystemConfig(key=key, value=value, is_secret=is_secret))


async def _persist_normalized_runtime_ai_config(
    session: AsyncSession,
    runtime_ai_config: RuntimeAIConfig,
) -> None:
    await upsert_system_config_values(
        session,
        {
            "AI_PROVIDER_PROFILES": (json.dumps(runtime_ai_config.profiles, sort_keys=True), False),
            "AI_PROVIDER_ROUTING": (json.dumps(runtime_ai_config.routing, sort_keys=True), False),
            "AI_PROVIDER_FALLBACKS": (json.dumps(runtime_ai_config.fallbacks, sort_keys=True), False),
        },
    )


async def reset_runtime_ai_caches(preload: bool = False) -> None:
    """Reset cached AI router and LLM singletons after runtime config changes."""
    from app.services.ai.llm import close_global_llm_client, get_global_llm_client
    from app.services.ai.router import close_smart_router

    await close_global_llm_client()
    await close_smart_router()

    if preload:
        await get_global_llm_client()


async def hydrate_runtime_settings_from_db(
    session: AsyncSession | None = None,
    *,
    persist_normalized: bool = True,
    commit: bool = False,
    reset_caches: bool = True,
) -> RuntimeAIConfig:
    """Load authoritative runtime settings from DB and apply them in-memory."""
    owns_session = session is None
    if owns_session:
        async with async_session_maker() as owned_session:
            return await hydrate_runtime_settings_from_db(
                owned_session,
                persist_normalized=persist_normalized,
                commit=commit,
                reset_caches=reset_caches,
            )

    assert session is not None
    result = await session.execute(select(SystemConfig))
    rows = result.scalars().all()
    row_map = {row.key: row.value or "" for row in rows}

    runtime_ai_config = normalize_runtime_ai_config(row_map)
    apply_runtime_settings(row_map, runtime_ai_config)

    if persist_normalized:
        await _persist_normalized_runtime_ai_config(session, runtime_ai_config)
        if commit:
            await session.commit()

    if reset_caches:
        await reset_runtime_ai_caches()

    logger.info(
        "Runtime settings hydrated from DB: default=%s profiles=%d",
        runtime_ai_config.routing.get("default", "default"),
        len(runtime_ai_config.profiles),
    )
    return runtime_ai_config
