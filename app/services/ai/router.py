"""
LiteLLM-Powered Smart Router for LLM Requests.

Replaces the custom OllamaClient/APIClient with a unified router that:
- Routes to any provider (Ollama, OpenAI, Anthropic, Groq, etc.) via one interface
- Automatic fallbacks: local model fails → cloud model takes over
- Per-task model selection: cheap models for simple tasks, expensive for complex
- Cost tracking, rate limiting, retry with exponential backoff
- Supports 100+ models through LiteLLM's unified API

Usage:
    router = get_smart_router()
    response = await router.generate("What ports are open?", task_type="tool_selection")
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.core.telemetry import record_llm_call
from app.services.ai.llm import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Task complexity tiers — determines which model to use
TASK_TIERS = {
    # Tier 1: Simple, deterministic tasks → cheapest/fastest model
    "scope": 1,
    "tool_selection": 1,
    "safety_check": 1,
    "parsing": 1,
    # Tier 2: Moderate reasoning → mid-tier model
    "planning": 2,
    "steering": 2,
    "consensus": 2,
    "vector_generation": 2,
    "reporting": 2,
    # Tier 3: Complex creative tasks → most capable model
    "exploit_crafting": 3,
    "poc_generation": 3,
    "post_exploitation": 3,
}

# Pre-configured provider profiles
PROVIDER_PRESETS = {
    "z.ai": {
        "name": "Z.AI (Zhipu GLM)",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "models": {
            "glm-4.7": {"tier": 3, "description": "Flagship coding model, 200K context"},
            "glm-4.7-flashx": {"tier": 2, "description": "Fast and affordable, 200K context"},
            "glm-4.7-flash": {"tier": 1, "description": "Free tier, lightweight"},
            "glm-5": {"tier": 3, "description": "Latest flagship, 744B MoE"},
        },
        "default_model": "glm-4.7-flash",
    },
    "qwen": {
        "name": "Qwen (Alibaba DashScope)",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "models": {
            "qwen3.5-397b-a17b": {"tier": 3, "description": "Qwen 3.5 flagship MoE, 397B params"},
            "qwen3.5-plus": {"tier": 2, "description": "Qwen 3.5 Plus, multimodal, 1M context"},
            "qwen3.5-flash": {"tier": 1, "description": "Qwen 3.5 Flash, fast, 1M context"},
            "qwen3-235b-a22b": {"tier": 3, "description": "Qwen 3 MoE, 22B active"},
            "qwen3-32b": {"tier": 2, "description": "32B dense, 128K context"},
            "qwen3-8b": {"tier": 1, "description": "8B dense, 128K context, fast"},
        },
        "default_model": "qwen3.5-plus",
    },
}

_CLOUD_PROVIDER_ALIASES = {"api", "openai", "litellm", "ollama"}


def _normalize_provider_name(provider: str | None) -> str:
    normalized = (provider or "litellm").strip().lower() or "litellm"
    if normalized in _CLOUD_PROVIDER_ALIASES:
        return "litellm"
    return normalized


def _resolve_litellm_model_name(model: str, *, base_url: str | None = None) -> str:
    if base_url and "/" not in model:
        return f"openai/{model}"
    return model


class LiteLLMRouter(LLMClient):
    """
    Smart LLM router powered by LiteLLM.

    Features:
    - Unified interface for all providers (Ollama, OpenAI, Anthropic, etc.)
    - Automatic fallbacks when a model/provider fails
    - Per-task model routing based on complexity
    - Cost tracking and rate limiting
    - Retry with exponential backoff
    """

    provider = "litellm"

    def __init__(
        self,
        model_configs: list[dict[str, Any]] | None = None,
        fallbacks: list[dict[str, list[str]]] | None = None,
        default_model: str = "openai/gpt-4o-mini",
    ):
        self._router = None
        self._model_configs = model_configs or []
        self._fallbacks = fallbacks or []
        self._default_model = default_model
        self._task_model_map: dict[int, str] = {}
        self._direct_fallback_warned = False

    def _get_router(self):
        """Lazy-initialize the LiteLLM router."""
        if self._router is not None:
            return self._router

        try:
            from litellm import Router

            if self._model_configs:
                self._router = Router(
                    model_list=self._model_configs,
                    fallbacks=self._fallbacks,
                    retry_after=2,
                    num_retries=2,
                    timeout=settings.LLM_TIMEOUT,
                    allowed_fails=3,
                )
                logger.info(
                    "LiteLLM Router initialized with %d model configs",
                    len(self._model_configs),
                )
            else:
                self._router = None

        except (OSError, RuntimeError, ValueError, ImportError) as e:
            logger.warning("Failed to initialize LiteLLM Router: %s", e)
            self._router = None

        return self._router

    def _get_model_for_task(self, task_type: str | None = None) -> str:
        """Select the best model based on task complexity."""
        if not task_type:
            return self._default_model

        tier = TASK_TIERS.get(task_type, 2)

        if tier in self._task_model_map:
            return self._task_model_map[tier]

        return self._default_model

    def configure_task_models(
        self,
        tier1_model: str | None = None,
        tier2_model: str | None = None,
        tier3_model: str | None = None,
    ) -> None:
        """Configure which models to use for each task tier."""
        if tier1_model:
            self._task_model_map[1] = tier1_model
        if tier2_model:
            self._task_model_map[2] = tier2_model
        if tier3_model:
            self._task_model_map[3] = tier3_model

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        """Generate text using LiteLLM with smart routing."""

        model = self._get_model_for_task(task_type)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start_time = time.time()

        try:
            router = self._get_router()
            if not router:
                raise RuntimeError("LiteLLM router is not initialized")

            response = await router.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout or settings.LLM_TIMEOUT,
            )

            choice = response.choices[0]
            usage = response.usage

            duration_ms = (time.time() - start_time) * 1000
            total_tokens = usage.total_tokens if usage else 0
            logger.debug(
                "LiteLLM [%s] %.0fms tokens=%d",
                model,
                duration_ms,
                total_tokens,
            )

            await record_llm_call(
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
                tokens=total_tokens,
                success=True,
            )

            return LLMResponse(
                content=choice.message.content or "",
                model=model,
                provider=self.provider,
                usage={
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
                raw={},
            )

        except (OSError, RuntimeError, ValueError, TimeoutError, ImportError) as e:
            duration_ms = (time.time() - start_time) * 1000
            await record_llm_call(
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
                tokens=0,
                success=False,
            )
            logger.error("LiteLLM generation failed for model %s: %s", model, e)
            raise

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens using litellm's streaming API."""
        import litellm

        model = self._get_model_for_task(task_type)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                timeout=timeout or settings.LLM_TIMEOUT,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except (OSError, RuntimeError, ValueError, TimeoutError):
            raise

    async def health_check(self) -> bool:
        """Check if the configured LLM is reachable."""
        try:
            response = await self.generate(
                "ping",
                max_tokens=5,
                temperature=0,
                timeout=10,
            )
            return bool(response.content)
        except (OSError, RuntimeError, ValueError, TimeoutError, ImportError):
            return False

    async def close(self) -> None:
        """Clean up resources."""
        self._router = None


def _build_legacy_model_config_from_settings() -> tuple[list[dict], list[dict], str]:
    """Build LiteLLM model configs from legacy flat settings."""
    model_list = []
    fallbacks = []
    default_model = "openai/gpt-4.1-mini"

    raw_provider = settings.AI_PROVIDER
    raw_lower = str(raw_provider or "litellm").strip().lower()

    if raw_lower == "ollama":
        ollama_model = f"ollama/{settings.OLLAMA_MODEL}"
        model_list.append(
            {
                "model_name": "default",
                "litellm_params": {
                    "model": ollama_model,
                    "api_base": settings.OLLAMA_HOST,
                },
            }
        )
        default_model = "default"

    else:
        api_key = settings.LLM_API_KEY.get_secret_value()
        if raw_lower in ("api", "openai") and not api_key:
            return [], [], default_model

        cloud_model = settings.LLM_MODEL or "glm-4.7"
        litellm_model = _resolve_litellm_model_name(
            cloud_model,
            base_url=settings.LLM_API_BASE_URL,
        )

        model_list.append(
            {
                "model_name": "default",
                "litellm_params": {
                    "model": litellm_model,
                    **({"api_key": api_key} if api_key else {}),
                    **({"api_base": settings.LLM_API_BASE_URL} if settings.LLM_API_BASE_URL else {}),
                },
            }
        )
        default_model = "default"

    # Register per-tier models as separate model groups in the LiteLLM router
    # so tier routing can reference them by name
    api_key_val = settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY else ""
    tier_models = {
        settings.LLM_TIER1_MODEL: "tier1",
        settings.LLM_TIER2_MODEL: "tier2",
        settings.LLM_TIER3_MODEL: "tier3",
    }
    registered_names = {cfg["model_name"] for cfg in model_list}
    for tier_model_name, group_name in tier_models.items():
        if not isinstance(tier_model_name, str) or not tier_model_name.strip():
            continue
        if group_name in registered_names:
            continue
        # Detect Ollama-style models by prefix or legacy provider
        if tier_model_name.startswith("ollama/") or raw_lower == "ollama":
            litellm_tier = tier_model_name if tier_model_name.startswith("ollama/") else f"ollama/{tier_model_name}"
        else:
            litellm_tier = _resolve_litellm_model_name(
                tier_model_name,
                base_url=settings.LLM_API_BASE_URL,
            )

        tier_params: dict[str, Any] = {"model": litellm_tier}
        if api_key_val:
            tier_params["api_key"] = api_key_val
        if settings.LLM_API_BASE_URL:
            tier_params["api_base"] = settings.LLM_API_BASE_URL
        elif raw_lower == "ollama" or litellm_tier.startswith("ollama/"):
            tier_params["api_base"] = settings.OLLAMA_HOST

        model_list.append(
            {
                "model_name": group_name,
                "litellm_params": tier_params,
            }
        )
    return model_list, fallbacks, default_model


def _build_model_config_for_profile(
    profile_name: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    model = str(profile.get("model", "")).strip()
    litellm_params: dict[str, Any] = {}

    if model.startswith("ollama/"):
        litellm_params = {
            "model": model,
            "api_base": profile.get("base_url") or settings.OLLAMA_HOST,
        }
    else:
        base_url = profile.get("base_url")
        litellm_params = {
            "model": _resolve_litellm_model_name(model, base_url=base_url),
        }
        if profile.get("api_key"):
            litellm_params["api_key"] = profile["api_key"]
        if base_url:
            litellm_params["api_base"] = base_url

    return {
        "model_name": profile_name,
        "litellm_params": litellm_params,
    }


def build_model_config_from_settings() -> tuple[list[dict], list[dict], str]:
    """Build LiteLLM model configs from the resolved provider-profile settings."""
    profiles = getattr(settings, "AI_PROVIDER_PROFILES", {}) or {}
    routing = getattr(settings, "AI_PROVIDER_ROUTING", {}) or {}
    fallbacks_map = getattr(settings, "AI_PROVIDER_FALLBACKS", {}) or {}

    if not profiles or routing.get("default") not in profiles:
        return _build_legacy_model_config_from_settings()

    model_list = [_build_model_config_for_profile(profile_name, profile) for profile_name, profile in profiles.items()]
    default_model = routing.get("default", "default")
    fallbacks: list[dict[str, list[str]]] = []
    seen_sources: set[str] = set()

    for route_name, fallback_profiles in fallbacks_map.items():
        source_profile = routing.get(route_name, default_model)
        filtered_targets = [name for name in fallback_profiles if name in profiles]
        if source_profile in profiles and filtered_targets and source_profile not in seen_sources:
            fallbacks.append({source_profile: filtered_targets})
            seen_sources.add(source_profile)

    return model_list, fallbacks, default_model


def create_smart_router() -> LLMClient:
    """Create a SmartRouter from current settings."""
    normalized_provider = _normalize_provider_name(settings.AI_PROVIDER)
    if normalized_provider == "mock":
        raise ValueError(
            "Unsupported LLM provider configured; the application runtime requires LiteLLM-backed providers."
        )

    model_list, fallbacks, default_model = build_model_config_from_settings()

    if not model_list:
        raise ValueError("No LLM model configuration resolved from current settings")

    router = LiteLLMRouter(
        model_configs=model_list,
        fallbacks=fallbacks,
        default_model=default_model,
    )

    routing = getattr(settings, "AI_PROVIDER_ROUTING", {}) or {}
    if routing:
        tier1 = routing.get("tier1")
        tier2 = routing.get("tier2")
        tier3 = routing.get("tier3")
    else:
        tier1 = settings.LLM_TIER1_MODEL
        tier2 = settings.LLM_TIER2_MODEL
        tier3 = settings.LLM_TIER3_MODEL

    if tier1 or tier2 or tier3:
        router.configure_task_models(
            tier1_model=tier1 or None,
            tier2_model=tier2 or None,
            tier3_model=tier3 or None,
        )
        logger.info(
            "Tier routing configured: T1=%s T2=%s T3=%s",
            tier1 or "(default)",
            tier2 or "(default)",
            tier3 or "(default)",
        )

    return router


# Singleton
_smart_router: LLMClient | None = None


def get_smart_router() -> LLMClient:
    """Get the global smart router instance."""
    global _smart_router
    if _smart_router is None:
        _smart_router = create_smart_router()
    return _smart_router


async def close_smart_router() -> None:
    """Close the smart router."""
    global _smart_router
    if _smart_router:
        await _smart_router.close()
        _smart_router = None
