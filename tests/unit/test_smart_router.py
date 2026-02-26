"""Tests for the LiteLLM Smart Router."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.ai.router import (
    LiteLLMRouter,
    TASK_TIERS,
    build_model_config_from_settings,
    create_smart_router,
    get_smart_router,
)
from app.services.ai.llm import LLMResponse


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
        """Test generation when no router configured (uses litellm.acompletion directly)."""
        router = LiteLLMRouter(default_model="gpt-4o-mini")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test response"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
        ):
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

        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
        ) as mock_call:
            await router.generate("select a tool", task_type="tool_selection")
            call_args = mock_call.call_args
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

        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
        ):
            assert await router.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        router = LiteLLMRouter()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, side_effect=Exception("down")
        ):
            assert await router.health_check() is False

    @pytest.mark.asyncio
    async def test_close(self):
        router = LiteLLMRouter()
        await router.close()
        assert router._router is None


class TestBuildModelConfig:
    def test_api_provider(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "api"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_MODEL = "gpt-4o"
            mock_settings.LLM_API_BASE_URL = None

            configs, fallbacks, default = build_model_config_from_settings()
            assert len(configs) == 1
            assert configs[0]["model_name"] == "default"
            assert default == "default"

    def test_ollama_with_cloud_fallback(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "ollama"
            mock_settings.OLLAMA_HOST = "http://localhost:11434"
            mock_settings.OLLAMA_MODEL = "qwen2.5:3b"
            mock_settings.LLM_API_KEY = MagicMock()
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-fallback"
            mock_settings.LLM_MODEL = "gpt-4o-mini"
            mock_settings.LLM_API_BASE_URL = None

            configs, fallbacks, default = build_model_config_from_settings()
            assert len(configs) == 2
            assert default == "default"
            assert len(fallbacks) == 1

    def test_mock_provider(self):
        with patch("app.services.ai.router.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "mock"

        router = create_smart_router()
        from app.services.ai.llm import MockLLMClient

        assert isinstance(router, MockLLMClient)

    def test_no_api_key(self):
        with patch("app.services.ai.router.settings") as mock_settings:
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
