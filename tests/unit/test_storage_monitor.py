"""Tests for StorageMonitor."""
import time
from unittest.mock import AsyncMock

import pytest

from app.services.infrastructure.storage_monitor import StorageMonitor


class TestCheckDiskUsage:
    def test_returns_usage_dict(self):
        result = StorageMonitor.check_disk_usage("/")
        assert "path" in result
        assert "total_gb" in result
        assert "used_gb" in result
        assert "free_gb" in result
        assert "pct_used" in result
        assert isinstance(result["pct_used"], float)

    def test_invalid_path_returns_error(self):
        result = StorageMonitor.check_disk_usage("/nonexistent/path/that/does/not/exist")
        assert "error" in result


class TestCheckS3Health:
    @pytest.mark.asyncio
    async def test_healthy(self):
        mock_storage = AsyncMock()
        mock_storage.health_check.return_value = True
        result = await StorageMonitor.check_s3_health(mock_storage)
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_unhealthy(self):
        mock_storage = AsyncMock()
        mock_storage.health_check.return_value = False
        result = await StorageMonitor.check_s3_health(mock_storage)
        assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_error(self):
        mock_storage = AsyncMock()
        mock_storage.health_check.side_effect = ConnectionError("timeout")
        result = await StorageMonitor.check_s3_health(mock_storage)
        assert result["status"] == "error"
        assert "timeout" in result["error"]


class TestAlertDedup:
    def setup_method(self):
        StorageMonitor._alert_cooldown.clear()

    def test_first_alert_allowed(self):
        assert StorageMonitor.should_alert("test_key") is True

    def test_repeat_alert_suppressed(self):
        StorageMonitor.should_alert("test_key")
        assert StorageMonitor.should_alert("test_key") is False

    def test_alert_after_cooldown(self):
        StorageMonitor.should_alert("test_key")
        # Manually set the cooldown timestamp to the past
        StorageMonitor._alert_cooldown["test_key"] = time.monotonic() - StorageMonitor.ALERT_COOLDOWN_SECS - 1
        assert StorageMonitor.should_alert("test_key") is True

    def test_different_keys_independent(self):
        StorageMonitor.should_alert("key_a")
        assert StorageMonitor.should_alert("key_b") is True


class TestGetFullStatus:
    @pytest.mark.asyncio
    async def test_without_storage_service(self):
        result = await StorageMonitor.get_full_status()
        assert "root_disk" in result
        assert "data_disk" in result
        assert "s3" not in result

    @pytest.mark.asyncio
    async def test_with_storage_service(self):
        mock_storage = AsyncMock()
        mock_storage.health_check.return_value = True
        result = await StorageMonitor.get_full_status(storage_service=mock_storage)
        assert "s3" in result
