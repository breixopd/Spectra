"""Tests for training dataset and fine-tuning system."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAnonymizeText:
    def test_removes_ips(self):
        from spectra_billing.training.dataset import anonymize_text

        result = anonymize_text("Scanning 192.168.1.1 found open port")
        assert "192.168.1.1" not in result
        assert "<IP_ADDR>" in result

    def test_removes_credentials(self):
        from spectra_billing.training.dataset import anonymize_text

        result = anonymize_text("Found password=admin123 in config")
        assert "admin123" not in result
        assert "<REDACTED>" in result

    def test_removes_paths(self):
        from spectra_billing.training.dataset import anonymize_text

        result = anonymize_text("Reading /home/user/secrets.txt")
        assert "/home/user" not in result
        assert "<PATH>" in result

    def test_preserves_technical_content(self):
        from spectra_billing.training.dataset import anonymize_text

        text = "Use nmap -sV -p 22,80,443 for service detection"
        result = anonymize_text(text)
        assert "nmap" in result
        assert "-sV" in result


@pytest.mark.asyncio
class TestTrainingRouter:
    async def test_dataset_stats_endpoint(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from spectra_api.api.routers.admin.training import router
        from spectra_auth.rate_limit import limiter

        app = FastAPI()
        app.state.limiter = limiter
        limiter.enabled = False
        app.include_router(router)

        user = MagicMock()
        user.id = "u-1"
        user.username = "admin"
        user.is_superuser = True
        user.role = "admin"
        user.is_active = True
        user.mfa_enabled = True
        user.mfa_secret = "enc"
        user.hashed_password = "h"
        user.invalidated_before = None

        from spectra_api.api.dependencies import get_current_active_user
        from spectra_persistence.database import get_async_session

        app.dependency_overrides[get_current_active_user] = lambda: user

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _gs():
            yield mock_session

        app.dependency_overrides[get_async_session] = _gs

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/admin/training/stats")
        assert resp.status_code == 200
        assert "types" in resp.json()

    async def test_providers_endpoint(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from spectra_api.api.routers.admin.training import router
        from spectra_auth.rate_limit import limiter

        app = FastAPI()
        app.state.limiter = limiter
        limiter.enabled = False
        app.include_router(router)

        user = MagicMock()
        user.id = "u-1"
        user.username = "admin"
        user.is_superuser = True
        user.role = "admin"
        user.is_active = True
        user.mfa_enabled = True
        user.mfa_secret = "enc"
        user.hashed_password = "h"
        user.invalidated_before = None

        from spectra_api.api.dependencies import get_current_active_user

        app.dependency_overrides[get_current_active_user] = lambda: user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/admin/training/providers")
        assert resp.status_code == 200
        data = resp.json()
        provider_ids = {provider["id"] for provider in data["providers"]}
        assert {"local", "custom", "runpod", "vast", "lambda", "modal"}.issubset(provider_ids)
        runpod = next(provider for provider in data["providers"] if provider["id"] == "runpod")
        assert "output_storage_uri" in runpod["config_fields"]
