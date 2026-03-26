"""Tests for the LiteLLM Smart Router."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agents.base import ROLE_TASK_MAP, AgentRole
from app.services.ai.router import (
    TASK_TIERS,
    LiteLLMRouter,
    build_model_config_from_settings,
    create_smart_router,
    get_smart_router,
)


class TestTaskTiers:
    def test_simple_tasks_are_tier1(self):
        assert TASK_TIERS["scope"] == 1
        assert TASK_TIERS["tool_selection"] == 1
        assert TASK_TIERS["safety_check"] == 1

    def test_moderate_tasks_are_tier2(self):
        assert TASK_TIERS["planning"] == 2
        assert TASK_TIERS["consensus"] == 2
        assert TASK_TIERS["reporting"] == 2

    def test_complex_tasks_are_tier3(self):
        assert TASK_TIERS["exploit_crafting"] == 3
        assert TASK_TIERS["poc_generation"] == 3
        assert TASK_TIERS["post_exploitation"] == 3


class TestLiteLLMRouter:
    def test_init_defaults(self):
        router = LiteLLMRouter()
        assert router._default_model == "openai/gpt-4o-mini"
        assert router._router is None

    def test_configure_task_models(self):
        router = LiteLLMRouter()
        router.configure_task_models(
            tier1_model="ollama/qwen2.5:3b",
            tier2_model="gpt-4o-mini",
            tier3_model="gpt-4o",
        )
        assert router._task_model_map[1] == "ollama/qwen2.5:3b"
        assert router._task_model_map[2] == "gpt-4o-mini"
        assert router._task_model_map[3] == "gpt-4o"

    def test_get_model_for_task_default(self):
        router = LiteLLMRouter(default_model="gpt-4o-mini")
        assert router._get_model_for_task(None) == "gpt-4o-mini"
        assert router._get_model_for_task("unknown_task") == "gpt-4o-mini"

    def test_get_model_for_task_with_tiers(self):
        router = LiteLLMRouter(default_model="default")
        router.configure_task_models(
            tier1_model="cheap",
            tier3_model="expensive",
        )
        assert router._get_model_for_task("scope") == "cheap"
        assert router._get_model_for_task("planning") == "default"
        assert router._get_model_for_task("exploit_crafting") == "expensive"

    @pytest.mark.asyncio
    async def test_generate_direct_litellm(self):
        """Test generation through the configured LiteLLM router instance."""
        router = LiteLLMRouter(default_model="gpt-4o-mini")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test response"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        router._router = types.SimpleNamespace(acompletion=AsyncMock(return_value=mock_response))
        result = await router.generate("hello")
        assert result.content == "test response"
        assert result.usage["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_generate_with_task_type(self):
        """Test that task_type selects the right model."""
        router = LiteLLMRouter(default_model="default-model")
        router.configure_task_models(tier1_model="cheap-model")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 10

        router._router = types.SimpleNamespace(acompletion=AsyncMock(return_value=mock_response))
        await router.generate("select a tool", task_type="tool_selection")
        call_args = router._router.acompletion.call_args
        assert call_args.kwargs["model"] == "cheap-model"

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        router = LiteLLMRouter()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "pong"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 1
        mock_response.usage.completion_tokens = 1
        mock_response.usage.total_tokens = 2

        router._router = types.SimpleNamespace(acompletion=AsyncMock(return_value=mock_response))
        assert await router.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        router = LiteLLMRouter()
        router._router = types.SimpleNamespace(acompletion=AsyncMock(side_effect=RuntimeError("down")))
        assert await router.health_check() is False

    @pytest.mark.asyncio
    async def test_close(self):
        router = LiteLLMRouter()
        await router.close()
        assert router._router is None


class TestBuildModelConfig:
    def test_legacy_api_provider_normalizes_to_unified_cloud_router(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER_PROFILES = {}
            mock_settings.AI_PROVIDER_ROUTING = {}
            mock_settings.AI_PROVIDER_FALLBACKS = {}
            mock_settings.AI_PROVIDER = "api"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_MODEL = "gpt-4o"
            mock_settings.LLM_API_BASE_URL = None
            mock_settings.OLLAMA_ENABLED = False

            configs, fallbacks, default = build_model_config_from_settings()
            assert len(configs) == 1
            assert configs[0]["model_name"] == "default"
            assert configs[0]["litellm_params"]["model"] == "gpt-4o"
            assert default == "default"
            assert fallbacks == []

    def test_ollama_without_implicit_cloud_fallback(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER_PROFILES = {}
            mock_settings.AI_PROVIDER_ROUTING = {}
            mock_settings.AI_PROVIDER_FALLBACKS = {}
            mock_settings.AI_PROVIDER = "ollama"
            mock_settings.OLLAMA_HOST = "http://localhost:11434"
            mock_settings.OLLAMA_MODEL = "qwen2.5:3b"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-fallback"
            mock_settings.LLM_MODEL = "gpt-4o-mini"
            mock_settings.LLM_API_BASE_URL = None

            configs, fallbacks, default = build_model_config_from_settings()
            assert len(configs) == 1
            assert default == "default"
            assert fallbacks == []

    def test_no_api_key(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER_PROFILES = {}
            mock_settings.AI_PROVIDER_ROUTING = {}
            mock_settings.AI_PROVIDER_FALLBACKS = {}
            mock_settings.AI_PROVIDER = "api"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""

            configs, fallbacks, default = build_model_config_from_settings()
            assert len(configs) == 0


class TestSingleton:
    def test_get_smart_router(self):
        import app.services.ai.router as mod

        mod._smart_router = None
        with patch("app.services.ai.router.create_smart_router") as mock_create:
            mock_create.return_value = MagicMock()
            r1 = get_smart_router()
            r2 = get_smart_router()
            assert r1 is r2
            mock_create.assert_called_once()
        mod._smart_router = None


class TestRoleTaskMap:
    """Tests that every AgentRole has a task mapping."""

    def test_all_roles_mapped(self):
        for role in AgentRole:
            assert role in ROLE_TASK_MAP, f"AgentRole.{role.name} missing from ROLE_TASK_MAP"

    def test_mapped_task_types_in_tiers(self):
        """Every task_type in ROLE_TASK_MAP should exist in TASK_TIERS."""
        for role, task_type in ROLE_TASK_MAP.items():
            assert task_type in TASK_TIERS, f"ROLE_TASK_MAP[{role.name}] = '{task_type}' not in TASK_TIERS"

    def test_exploit_crafter_is_tier3(self):
        task = ROLE_TASK_MAP[AgentRole.EXPLOIT_CRAFTER]
        assert TASK_TIERS[task] == 3

    def test_scope_is_tier1(self):
        task = ROLE_TASK_MAP[AgentRole.SCOPE]
        assert TASK_TIERS[task] == 1

    def test_reporter_is_tier2(self):
        task = ROLE_TASK_MAP[AgentRole.REPORTER]
        assert TASK_TIERS[task] == 2


class TestCreateSmartRouterTierWiring:
    """Tests that create_smart_router wires tier models from settings."""

    def test_tier_models_wired(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER_PROFILES = {}
            mock_settings.AI_PROVIDER_ROUTING = {}
            mock_settings.AI_PROVIDER_FALLBACKS = {}
            mock_settings.AI_PROVIDER = "ollama"
            mock_settings.OLLAMA_HOST = "http://localhost:11434"
            mock_settings.OLLAMA_MODEL = "qwen2.5:7b"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            mock_settings.LLM_TIMEOUT = 600.0
            mock_settings.LLM_TIER1_MODEL = "ollama/qwen2.5:3b"
            mock_settings.LLM_TIER2_MODEL = ""
            mock_settings.LLM_TIER3_MODEL = "ollama/qwen2.5:14b"

            router = create_smart_router()

        assert isinstance(router, LiteLLMRouter)
        assert router._task_model_map[1] == "ollama/qwen2.5:3b"
        assert 2 not in router._task_model_map
        assert router._task_model_map[3] == "ollama/qwen2.5:14b"

    def test_no_tier_models_no_map(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER_PROFILES = {}
            mock_settings.AI_PROVIDER_ROUTING = {}
            mock_settings.AI_PROVIDER_FALLBACKS = {}
            mock_settings.AI_PROVIDER = "ollama"
            mock_settings.OLLAMA_HOST = "http://localhost:11434"
            mock_settings.OLLAMA_MODEL = "qwen2.5:7b"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            mock_settings.LLM_TIMEOUT = 600.0
            mock_settings.LLM_TIER1_MODEL = ""
            mock_settings.LLM_TIER2_MODEL = ""
            mock_settings.LLM_TIER3_MODEL = ""

            router = create_smart_router()

        assert isinstance(router, LiteLLMRouter)

    def test_profile_based_routing_uses_profile_names(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "api"
            mock_settings.LLM_TIMEOUT = 600.0
            mock_settings.AI_PROVIDER_PROFILES = {
                "default": {
                    "provider": "api",
                    "model": "gpt-4o-mini",
                    "api_key": "sk-test",
                    "base_url": "https://example.test/v1",
                },
                "research": {
                    "provider": "ollama",
                    "model": "qwen2.5:7b",
                    "base_url": "http://ollama:11434",
                },
            }
            mock_settings.AI_PROVIDER_ROUTING = {
                "default": "default",
                "tier1": "research",
            }
            mock_settings.AI_PROVIDER_FALLBACKS = {"tier1": ["default"]}

            configs, fallbacks, default = build_model_config_from_settings()
            router = create_smart_router()

        assert {config["model_name"] for config in configs} == {"default", "research"}
        default_config = next(config for config in configs if config["model_name"] == "default")
        assert default_config["litellm_params"]["model"] == "openai/gpt-4o-mini"
        assert fallbacks == [{"research": ["default"]}]
        assert default == "default"
        assert isinstance(router, LiteLLMRouter)
        assert router._task_model_map[1] == "research"
        assert 2 not in router._task_model_map


class TestLiteLLMProvider:
    """Tests for the litellm provider in build_model_config_from_settings."""

    def test_litellm_provider_basic(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "tensorzero"
            mock_settings.LLM_MODEL = "ollama/qwen2.5:7b"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            mock_settings.LLM_API_BASE_URL = None

            configs, fallbacks, default = build_model_config_from_settings()

        assert len(configs) == 1
        assert configs[0]["litellm_params"]["model"] == "ollama/qwen2.5:7b"
        assert "api_key" not in configs[0]["litellm_params"]
        assert default == "default"

    def test_litellm_provider_with_api_key(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "tensorzero"
            mock_settings.LLM_MODEL = "anthropic/claude-3-haiku"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-ant-test"
            mock_settings.LLM_API_BASE_URL = None

            configs, _, _ = build_model_config_from_settings()

        assert configs[0]["litellm_params"]["api_key"] == "sk-ant-test"
