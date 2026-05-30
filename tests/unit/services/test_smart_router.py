"""Tests for the TensorZero smart router."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from spectra_ai.router import (
    TASK_TIERS,
    TensorZeroRouter,
    close_smart_router,
    create_smart_router,
    get_smart_router,
)
from spectra_ai_core.agents.base import ROLE_TASK_MAP, AgentRole


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


class TestTensorZeroRouter:
    def test_init_defaults(self):
        mock_s = MagicMock()
        mock_s.TENSORZERO_GATEWAY_URL = "http://tensorzero:3000"
        mock_s.LLM_TIMEOUT = 120.0
        with patch("spectra_ai.router.get_ai_settings", return_value=mock_s):
            router = TensorZeroRouter()
        assert router._gateway_url == "http://tensorzero:3000"
        assert router._client is None

    def test_get_function_for_task(self):
        router = TensorZeroRouter(gateway_url="http://tensorzero:3000")
        assert router._get_function_for_task(None) == "default"
        assert router._get_function_for_task("unknown") == "default"
        assert router._get_function_for_task("scope") == "scope"
        assert router._get_function_for_task("exploit_crafting") == "exploit_crafting"

    @pytest.mark.asyncio
    async def test_generate_success(self):
        router = TensorZeroRouter(gateway_url="http://tensorzero:3000")
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(
            return_value=MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(
                    return_value={
                        "content": [{"type": "text", "text": "test response"}],
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                        "variant_name": "fast-primary",
                        "inference_id": "inf-123",
                        "episode_id": "ep-123",
                    }
                ),
            )
        )
        router._client = mock_client

        result = await router.generate("hello", task_type="tool_selection")
        assert result.content == "test response"
        assert result.provider == "tensorzero"
        assert result.usage["total_tokens"] == 30
        assert result.model == "tool_selection/fast-primary"
        assert result.raw["inference_id"] == "inf-123"
        call = mock_client.post.call_args
        assert call.args[0] == "/inference"
        assert call.kwargs["json"]["function_name"] == "tool_selection"

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        router = TensorZeroRouter(gateway_url="http://tensorzero:3000")
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        router._client = mock_client
        assert await router.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        router = TensorZeroRouter(gateway_url="http://tensorzero:3000")
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
        router._client = mock_client
        assert await router.health_check() is False

    @pytest.mark.asyncio
    async def test_close(self):
        router = TensorZeroRouter(gateway_url="http://tensorzero:3000")
        mock_client = MagicMock(is_closed=False)
        mock_client.aclose = AsyncMock()
        router._client = mock_client
        await router.close()
        mock_client.aclose.assert_awaited_once()
        assert router._client is None


class TestSingleton:
    def test_get_smart_router(self):
        import spectra_ai.router as mod

        mod._smart_router = None
        with patch("spectra_ai.router.create_smart_router") as mock_create:
            mock_create.return_value = MagicMock()
            r1 = get_smart_router()
            r2 = get_smart_router()
            assert r1 is r2
            mock_create.assert_called_once()
        mod._smart_router = None

    @pytest.mark.asyncio
    async def test_close_smart_router(self):
        import spectra_ai.router as mod

        mock_router = MagicMock()
        mock_router.close = AsyncMock()
        mod._smart_router = mock_router
        await close_smart_router()
        mock_router.close.assert_awaited_once()
        assert mod._smart_router is None


class TestCreateSmartRouter:
    def test_create_requires_gateway_url(self):
        mock_s = MagicMock()
        mock_s.TENSORZERO_GATEWAY_URL = ""
        mock_s.LLM_TIMEOUT = 120.0
        with patch("spectra_ai.router.get_ai_settings", return_value=mock_s):
            with pytest.raises(ValueError, match="TENSORZERO_GATEWAY_URL"):
                create_smart_router()

    def test_create_router_success(self):
        mock_s = MagicMock()
        mock_s.TENSORZERO_GATEWAY_URL = "http://tensorzero:3000"
        mock_s.LLM_TIMEOUT = 120.0
        with patch("spectra_ai.router.get_ai_settings", return_value=mock_s):
            router = create_smart_router()
        assert isinstance(router, TensorZeroRouter)
        assert router._gateway_url == "http://tensorzero:3000"


class TestRoleTaskMap:
    def test_all_roles_mapped(self):
        for role in AgentRole:
            assert role in ROLE_TASK_MAP, f"AgentRole.{role.name} missing from ROLE_TASK_MAP"

    def test_mapped_task_types_in_tiers(self):
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
