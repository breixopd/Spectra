from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routers.admin import tensorzero


class _FakeRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_tz_update_config_rejects_invalid_provider_type(tmp_path: Path):
    config_path = tmp_path / "tensorzero.toml"
    request = _FakeRequest(
        {
            "provider_type": "openai\n[metrics.injected]",
            "models": {"fast": "gpt-4o-mini", "balanced": "gpt-4o", "capable": "gpt-5"},
        }
    )

    with patch.object(tensorzero, "_CONFIG_PATH", config_path):
        with pytest.raises(HTTPException) as excinfo:
            await tensorzero.tz_update_config(request=request, _user=MagicMock())

    assert excinfo.value.status_code == 422
    assert not config_path.exists()


@pytest.mark.asyncio
async def test_tz_update_config_rejects_invalid_model_name(tmp_path: Path):
    config_path = tmp_path / "tensorzero.toml"
    request = _FakeRequest(
        {
            "provider_type": "openai",
            "models": {"fast": {"primary": "gpt-4o\n[bad]", "fallback": ""}, "balanced": "gpt-4o", "capable": "gpt-5"},
        }
    )

    with patch.object(tensorzero, "_CONFIG_PATH", config_path):
        with pytest.raises(HTTPException) as excinfo:
            await tensorzero.tz_update_config(request=request, _user=MagicMock())

    assert excinfo.value.status_code == 422
    assert not config_path.exists()
