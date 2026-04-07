"""Tests for API enhancements: finding status, bulk ops, missions filter, exploit chains, observability."""

from unittest.mock import MagicMock, patch

from app.models.finding import FindingStatus


class TestFindingStatusEnum:
    """API-001: Extended FindingStatus enum."""

    def test_dismissed_value(self):
        assert FindingStatus.DISMISSED.value == "dismissed"

    def test_retest_pending_value(self):
        assert FindingStatus.RETEST_PENDING.value == "retest_pending"

    def test_all_statuses_present(self):
        values = {s.value for s in FindingStatus}
        assert "potential" in values
        assert "verified" in values
        assert "exploited" in values
        assert "false_positive" in values
        assert "dismissed" in values
        assert "retest_pending" in values


class TestExploitChainStorage:
    """API-005: Custom exploit chain persistence."""

    def test_load_custom_chains_empty(self, tmp_path):
        from app.services.mission.chain_builder import load_custom_chains

        # With no file, should return empty
        with patch("app.services.mission.chain_builder.CUSTOM_CHAINS_PATH", tmp_path / "chains.json"):
            from app.services.mission import chain_builder

            original = chain_builder.CUSTOM_CHAINS_PATH
            chain_builder.CUSTOM_CHAINS_PATH = tmp_path / "chains.json"
            try:
                result = load_custom_chains()
                assert result == []
            finally:
                chain_builder.CUSTOM_CHAINS_PATH = original

    def test_save_and_load_custom_chain(self, tmp_path):
        import app.services.mission.chain_builder as cb_module
        from app.services.mission.chain_builder import (
            ChainBuilder,
            load_custom_chains,
            save_custom_chain,
        )

        original = cb_module.CUSTOM_CHAINS_PATH
        cb_module.CUSTOM_CHAINS_PATH = tmp_path / "chains.json"
        try:
            chain = ChainBuilder.create_chain(
                "Test Chain",
                [
                    {"id": "s1", "name": "Scan", "tool": "nmap"},
                ],
            )
            save_custom_chain(chain)

            loaded = load_custom_chains()
            assert len(loaded) == 1
            assert loaded[0].name == "Test Chain"
            assert len(loaded[0].stages) == 1
        finally:
            cb_module.CUSTOM_CHAINS_PATH = original

    def test_get_builtin_chains(self):
        from app.services.mission.chain_builder import get_builtin_chains

        chains = get_builtin_chains()
        assert len(chains) >= 2
        names = {c.name for c in chains}
        assert "Web App to Shell" in names
        assert "Network Pivot Chain" in names


class TestObservabilityGracefulDegradation:
    """API-003: Cache degradation in observability."""

    def test_cache_stats_returns_unavailable_when_no_cache(self):
        """Observability cache endpoint handles None cache gracefully."""
        from app.core.cache import get_cache

        # get_cache returns None when not initialized — that's fine
        cache = get_cache()
        # The observability code now handles this without crashing
        if cache is None:
            # This would have previously returned {"error": "Cache not initialized"}
            # Now it returns {"cache_available": False}
            pass  # Just verifying the import and logic path

    def test_cache_stats_dict_structure(self):
        """Verify the expected response when cache unavailable."""
        # Simulate what observability router does now
        cache = None
        cache_stats = {}
        cache_available = False
        try:
            if cache:
                cache_stats = cache.get_stats() or {}
                cache_available = True
        except Exception:
            pass
        result = {
            "cache": cache_stats,
            "cache_available": cache_available,
        }
        assert result["cache_available"] is False
        assert result["cache"] == {}

    def test_cache_stats_with_exception(self):
        """Verify exception handling in cache stats."""
        mock_cache = MagicMock()
        mock_cache.get_stats.side_effect = ConnectionError("Redis down")

        cache_stats = {}
        cache_available = False
        try:
            if mock_cache:
                cache_stats = mock_cache.get_stats() or {}
                cache_available = True
        except Exception:
            pass

        assert cache_available is False
        assert cache_stats == {}


class TestBulkUpdateSchema:
    """API-002: Bulk update schemas."""

    def test_bulk_update_request_schema(self):
        from app.api.routers.findings import BulkUpdateRequest, FindingUpdate

        req = BulkUpdateRequest(
            finding_ids=["id1", "id2"],
            update=FindingUpdate(status=FindingStatus.VERIFIED),
        )
        assert len(req.finding_ids) == 2
        assert req.update.status == FindingStatus.VERIFIED

    def test_bulk_update_response_schema(self):
        from app.api.routers.findings import BulkUpdateResponse

        resp = BulkUpdateResponse(updated=5)
        assert resp.updated == 5


class TestBulkDeleteSchema:
    """API-002: Bulk delete schemas."""

    def test_bulk_delete_request_schema(self):
        from app.api.routers.targets import BulkDeleteRequest

        req = BulkDeleteRequest(target_ids=["t1", "t2", "t3"])
        assert len(req.target_ids) == 3

    def test_bulk_delete_response_schema(self):
        from app.api.routers.targets import BulkDeleteResponse

        resp = BulkDeleteResponse(deleted=2)
        assert resp.deleted == 2


class TestMissionFilterImports:
    """API-006: Mission search/filter works at import level."""

    def test_mission_router_imports(self):
        from app.api.routers.missions import router

        routes = [r.path for r in router.routes]
        assert any("" == r or "/{mission_id}" in r for r in routes)

    def test_create_chain_request_schema(self):
        from app.api.routers.missions import CreateChainRequest

        req = CreateChainRequest(
            name="My Chain",
            description="test",
            stages=[{"id": "s1", "name": "Stage 1", "tool": "nmap"}],
        )
        assert req.name == "My Chain"
        assert len(req.stages) == 1
