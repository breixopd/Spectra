"""Tests for tiered resource profiles."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestGetTierLimits:
    """Tests for SandboxPool.get_tier_limits()."""

    def test_light_tier_returns_correct_limits(self):
        from app.services.tools.sandbox.pool import SandboxPool
        default_tiers = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
        with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_RESOURCE_TIERS=default_tiers)
            memory, cpu = SandboxPool.get_tier_limits("light")
            assert memory == "512m"
            assert cpu == 256

    def test_heavy_tier_returns_correct_limits(self):
        from app.services.tools.sandbox.pool import SandboxPool
        default_tiers = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
        with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_RESOURCE_TIERS=default_tiers)
            memory, cpu = SandboxPool.get_tier_limits("heavy")
            assert memory == "4g"
            assert cpu == 1024

    def test_unknown_tier_falls_back_to_medium(self):
        from app.services.tools.sandbox.pool import SandboxPool
        default_tiers = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
        with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_RESOURCE_TIERS=default_tiers)
            memory, cpu = SandboxPool.get_tier_limits("nonexistent")
            assert memory == "2g"
            assert cpu == 512

    def test_extreme_tier(self):
        from app.services.tools.sandbox.pool import SandboxPool
        default_tiers = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
        with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_RESOURCE_TIERS=default_tiers)
            memory, cpu = SandboxPool.get_tier_limits("extreme")
            assert memory == "8g"
            assert cpu == 2048

    def test_custom_tiers_from_settings(self):
        from app.services.tools.sandbox.pool import SandboxPool
        custom = '{"medium": {"memory": "16g", "cpu_shares": 4096}}'
        with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SANDBOX_RESOURCE_TIERS=custom)
            memory, cpu = SandboxPool.get_tier_limits("medium")
            assert memory == "16g"
            assert cpu == 4096


class TestPluginResourceTiers:
    """Tests that plugin JSONs have valid resource tiers."""

    def test_all_plugins_have_resources_field(self):
        from pathlib import Path
        plugins_dir = Path("plugins")
        if not plugins_dir.exists():
            pytest.skip("plugins directory not found")
        for f in plugins_dir.glob("*.json"):
            data = json.loads(f.read_text())
            assert "resources" in data, f"Plugin {f.name} missing resources field"
            assert "tier" in data["resources"], f"Plugin {f.name} missing resources.tier"

    def test_all_plugin_tiers_are_valid(self):
        from pathlib import Path
        valid_tiers = {"light", "medium", "heavy", "extreme"}
        plugins_dir = Path("plugins")
        if not plugins_dir.exists():
            pytest.skip("plugins directory not found")
        for f in plugins_dir.glob("*.json"):
            data = json.loads(f.read_text())
            tier = data.get("resources", {}).get("tier")
            assert tier in valid_tiers, f"Plugin {f.name} has invalid tier: {tier}"


class TestSandboxInfoResourceTier:
    """SandboxInfo dataclass includes resource_tier field."""

    def test_sandbox_info_has_resource_tier(self):

        from app.services.tools.sandbox.models import SandboxInfo
        info = SandboxInfo(
            container_id="abc", container_name="test", mission_id="m1",
            queue_name="q1", status="running", image="spectra-tools",
            resource_tier="heavy",
        )
        assert info.resource_tier == "heavy"

    def test_sandbox_info_default_resource_tier(self):
        from app.services.tools.sandbox.models import SandboxInfo
        info = SandboxInfo(
            container_id="abc", container_name="test", mission_id="m1",
            queue_name="q1", status="running", image="spectra-tools",
        )
        assert info.resource_tier == "medium"
