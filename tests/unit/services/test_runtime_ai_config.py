"""Tests for runtime AI configuration."""

import pytest

from app.services.system.runtime_ai_config import apply_ai_settings, get_current_ai_config


class FakeSettings:
    TENSORZERO_GATEWAY_URL = "http://gateway:3000"
    EMBEDDING_MODEL = "local/test"


def test_get_current_ai_config_returns_dict():
    result = get_current_ai_config()
    assert isinstance(result, dict)
    assert "gateway_url" in result
    assert "embedding_model" in result
    assert "timeout" in result


@pytest.mark.asyncio
async def test_apply_ai_settings_empty_rows():
    result = await apply_ai_settings({}, FakeSettings())
    assert result == {}


@pytest.mark.asyncio
async def test_apply_ai_settings_changes_detected():
    rows = {
        "TENSORZERO_GATEWAY_URL": "http://new:3000",
        "EMBEDDING_MODEL": "new-model",
        "LLM_TIMEOUT": "120",
    }
    result = await apply_ai_settings(rows, FakeSettings())
    assert "TENSORZERO_GATEWAY_URL" in result
    assert "EMBEDDING_MODEL" in result
    assert "LLM_TIMEOUT" in result
    assert result["TENSORZERO_GATEWAY_URL"] == ("http://new:3000", False)
    assert result["EMBEDDING_MODEL"] == ("new-model", False)
    assert result["LLM_TIMEOUT"] == ("120", False)


@pytest.mark.asyncio
async def test_apply_ai_settings_api_key_marked_sensitive():
    rows = {"TENSORZERO_API_KEY": "secret123"}
    result = await apply_ai_settings(rows, FakeSettings())
    assert result["TENSORZERO_API_KEY"] == ("secret123", True)


@pytest.mark.asyncio
async def test_apply_ai_settings_skips_unchanged():
    rows = {
        "TENSORZERO_GATEWAY_URL": "http://gateway:3000",
        "EMBEDDING_MODEL": "local/test",
    }
    result = await apply_ai_settings(rows, FakeSettings())
    assert "TENSORZERO_GATEWAY_URL" not in result
    assert "EMBEDDING_MODEL" not in result
