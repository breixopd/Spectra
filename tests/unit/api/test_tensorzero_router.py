from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from spectra_api.api.routers.admin import tensorzero


class _FakeRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


def _seed_config(path: Path) -> None:
    """Write a minimal but realistic DeepSeek gateway config to round-trip from."""
    path.write_text(
        """
[gateway]
bind_address = "0.0.0.0:3000"

[models.fast]
routing = ["primary"]

[models.fast.providers.primary]
type = "deepseek"
model_name = "deepseek-v4-flash"
api_key_location = "env::DEEPSEEK_API_KEY"
extra_body = [{ "pointer" = "/thinking/type", "value" = "disabled" }]

[models.balanced]
routing = ["primary"]

[models.balanced.providers.primary]
type = "deepseek"
model_name = "deepseek-v4-flash"
api_key_location = "env::DEEPSEEK_API_KEY"
extra_body = [{ "pointer" = "/thinking/type", "value" = "enabled" }]

[models.capable]
routing = ["primary"]

[models.capable.providers.primary]
type = "deepseek"
model_name = "deepseek-v4-pro"
api_key_location = "env::DEEPSEEK_API_KEY"
extra_body = [{ "pointer" = "/thinking/type", "value" = "enabled" }]

[functions.scope]
type = "chat"

[functions.scope.variants.default]
type = "chat_completion"
model = "fast"

[metrics.task_success]
type = "boolean"
level = "inference"
optimize = "max"
""".lstrip()
    )


@pytest.mark.asyncio
async def test_tz_update_config_rejects_deprecated_model(tmp_path: Path):
    config_path = tmp_path / "tensorzero.toml"
    _seed_config(config_path)
    # deepseek-reasoner is a deprecated alias — must be rejected.
    request = _FakeRequest({"models": {"fast": "deepseek-reasoner"}})

    with patch.object(tensorzero, "_CONFIG_PATH", config_path), pytest.raises(HTTPException) as excinfo:
        await tensorzero.tz_update_config(request=request, _user=MagicMock())

    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_tz_update_config_rejects_injection_in_model_name(tmp_path: Path):
    config_path = tmp_path / "tensorzero.toml"
    _seed_config(config_path)
    request = _FakeRequest({"models": {"fast": {"primary": "deepseek-v4-pro\n[bad]"}}})

    with patch.object(tensorzero, "_CONFIG_PATH", config_path), pytest.raises(HTTPException) as excinfo:
        await tensorzero.tz_update_config(request=request, _user=MagicMock())

    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_tz_update_config_preserves_thinking_and_functions(tmp_path: Path):
    """Swapping the capable-tier model must keep thinking config + functions/metrics intact."""
    import tomllib

    config_path = tmp_path / "tensorzero.toml"
    _seed_config(config_path)
    # Promote the fast tier to v4-pro; leave others unset (preserve current).
    request = _FakeRequest({"models": {"fast": "deepseek-v4-pro"}})

    with (
        patch.object(tensorzero, "_CONFIG_PATH", config_path),
        patch("spectra_scaling.docker_client.restart_service", new=AsyncMock(return_value=False)),
    ):
        result = await tensorzero.tz_update_config(request=request, _user=MagicMock())

    assert result["status"] == "ok"
    written = tomllib.loads(config_path.read_text())
    fast_primary = written["models"]["fast"]["providers"]["primary"]
    assert fast_primary["model_name"] == "deepseek-v4-pro"
    assert fast_primary["type"] == "deepseek"
    # thinking extra_body preserved
    assert {"pointer": "/thinking/type", "value": "disabled"} in fast_primary["extra_body"]
    # untouched tiers preserved
    assert written["models"]["capable"]["providers"]["primary"]["model_name"] == "deepseek-v4-pro"
    # functions + metrics preserved
    assert written["functions"]["scope"]["variants"]["default"]["model"] == "fast"
    assert written["metrics"]["task_success"]["optimize"] == "max"


@pytest.mark.asyncio
async def test_tz_config_reports_models_and_thinking(tmp_path: Path):
    config_path = tmp_path / "tensorzero.toml"
    _seed_config(config_path)

    with patch.object(tensorzero, "_CONFIG_PATH", config_path):
        result = await tensorzero.tz_config(_user=MagicMock())

    assert result["provider_type"] == "deepseek"
    assert result["allowed_models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert result["models"]["capable"] == {"model": "deepseek-v4-pro", "thinking": "enabled"}
    assert result["models"]["fast"]["thinking"] == "disabled"
