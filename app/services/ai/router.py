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
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.llm import LLMClient, LLMResponse, MockLLMClient

logger = logging.getLogger("spectra.ai.router")

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
        "name": "Z.AI (Zhipu)",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "models": {
            "glm-4.7": {"tier": 3, "description": "Flagship coding model, 200K context"},
            "glm-4.7-flashx": {"tier": 2, "description": "Fast and affordable, 200K context"},
            "glm-4.7-flash": {"tier": 1, "description": "Free tier, lightweight"},
            "glm-5": {"tier": 3, "description": "Latest flagship, 744B MoE"},
        },
        "default_model": "glm-4.7",
    },
    "kimi": {
        "name": "Kimi (Moonshot AI)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": {
            "kimi-k2.5": {"tier": 3, "description": "1T params, 256K context, multimodal"},
            "moonshot-v1-128k": {"tier": 2, "description": "128K context, balanced"},
            "moonshot-v1-32k": {"tier": 1, "description": "32K context, fast"},
        },
        "default_model": "kimi-k2.5",
    },
    "qwen": {
        "name": "Qwen (Alibaba)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": {
            "qwen3-235b-a22b": {"tier": 3, "description": "Flagship MoE, 22B active"},
            "qwen3-32b": {"tier": 2, "description": "32B dense, 128K context"},
            "qwen3-8b": {"tier": 1, "description": "8B dense, 128K context, fast"},
            "qwen3-14b": {"tier": 2, "description": "14B dense, 128K context"},
        },
        "default_model": "qwen3-32b",
    },
    "openrouter": {
        "name": "OpenRouter (Multi-provider)",
        "base_url": "https://openrouter.ai/api/v1",
        "models": {
            "qwen/qwen3-8b:free": {"tier": 1, "description": "Qwen3 8B, free"},
            "qwen/qwen3-32b": {"tier": 2, "description": "Qwen3 32B"},
            "anthropic/claude-3.5-sonnet": {"tier": 3, "description": "Claude 3.5 Sonnet"},
            "google/gemini-2.5-flash": {"tier": 2, "description": "Gemini 2.5 Flash"},
        },
        "default_model": "qwen/qwen3-8b:free",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": None,
        "models": {
            "gpt-4.1-mini": {"tier": 1, "description": "Fast and affordable"},
            "gpt-4.1": {"tier": 2, "description": "Balanced performance"},
            "o3-mini": {"tier": 3, "description": "Reasoning model"},
        },
        "default_model": "gpt-4.1-mini",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "base_url": None,
        "models": {
            "qwen3:8b": {"tier": 1, "description": "Qwen3 8B local"},
            "qwen3:14b": {"tier": 2, "description": "Qwen3 14B local"},
            "qwen3:32b": {"tier": 3, "description": "Qwen3 32B local (needs 24GB+ RAM)"},
            "llama3.3:8b": {"tier": 1, "description": "Llama 3.3 8B local"},
            "deepseek-r1:8b": {"tier": 2, "description": "DeepSeek R1 8B reasoning"},
        },
        "default_model": "qwen3:8b",
    },
}


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

        except Exception as e:
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
        import litellm

        model = self._get_model_for_task(task_type)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start_time = time.time()

        try:
            router = self._get_router()

            if router:
                response = await router.acompletion(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout or settings.LLM_TIMEOUT,
                )
            else:
                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout or settings.LLM_TIMEOUT,
                )

            choice = response.choices[0]
            usage = response.usage

            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                "LiteLLM [%s] %.0fms tokens=%d",
                model,
                duration_ms,
                usage.total_tokens if usage else 0,
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

        except Exception as e:
            logger.error("LiteLLM generation failed for model %s: %s", model, e)
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
        except Exception:
            return False

    async def close(self) -> None:
        """Clean up resources."""
        self._router = None


def build_model_config_from_settings() -> tuple[list[dict], list[dict], str]:
    """Build LiteLLM model configs from current app settings."""
    model_list = []
    fallbacks = []
    default_model = "openai/gpt-4.1-mini"

    provider = settings.AI_PROVIDER

    if provider == "ollama":
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

        # Add cloud fallback if API key is configured
        api_key = settings.LLM_API_KEY.get_secret_value()
        if api_key:
            cloud_model = settings.LLM_MODEL or "glm-4.7-flash"
            model_list.append(
                {
                    "model_name": "cloud-fallback",
                    "litellm_params": {
                        "model": cloud_model,
                        "api_key": api_key,
                        **(
                            {"api_base": settings.LLM_API_BASE_URL}
                            if settings.LLM_API_BASE_URL
                            else {}
                        ),
                    },
                }
            )
            fallbacks.append({"default": ["cloud-fallback"]})

    elif provider in ("api", "openai"):
        api_key = settings.LLM_API_KEY.get_secret_value()
        if not api_key:
            return [], [], default_model

        cloud_model = settings.LLM_MODEL or "glm-4.7"

        # Custom base URL means OpenAI-compatible provider (Z.AI, Kimi, Qwen, etc.)
        if settings.LLM_API_BASE_URL:
            litellm_model = f"openai/{cloud_model}"
        else:
            litellm_model = cloud_model

        model_list.append(
            {
                "model_name": "default",
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": api_key,
                    **(
                        {"api_base": settings.LLM_API_BASE_URL}
                        if settings.LLM_API_BASE_URL
                        else {}
                    ),
                },
            }
        )
        default_model = "default"

    return model_list, fallbacks, default_model


def create_smart_router() -> LLMClient:
    """Create a SmartRouter from current settings."""
    if settings.AI_PROVIDER == "mock":
        return MockLLMClient()

    model_list, fallbacks, default_model = build_model_config_from_settings()

    if not model_list:
        logger.warning("No model configs, falling back to direct LiteLLM calls")
        return LiteLLMRouter(default_model=default_model)

    router = LiteLLMRouter(
        model_configs=model_list,
        fallbacks=fallbacks,
        default_model=default_model,
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
