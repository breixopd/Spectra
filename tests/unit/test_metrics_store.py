"""Unit tests for MetricsStore (app/core/metrics_store.py)."""

import time
from unittest.mock import patch

from app.core.metrics_store import MetricsStore, get_metrics_store


class TestMetricsStoreCreation:
    def test_default_parameters(self):
        store = MetricsStore()
        assert store._history.maxlen == 1440
        assert store._interval == 60

    def test_custom_parameters(self):
        store = MetricsStore(max_history=100, interval_seconds=30)
        assert store._history.maxlen == 100
        assert store._interval == 30

    def test_history_starts_empty(self):
        store = MetricsStore()
        assert len(store._history) == 0

    def test_task_initially_none(self):
        store = MetricsStore()
        assert store._task is None


class TestGetHistory:
    def test_empty_store_returns_empty_list(self):
        store = MetricsStore()
        assert store.get_history() == []

    def test_empty_store_with_custom_window(self):
        store = MetricsStore()
        assert store.get_history(minutes=5) == []

    def test_returns_recent_entries_only(self):
        store = MetricsStore()
        now = time.time()
        # Old entry (2 hours ago)
        store._history.append({"_timestamp": now - 7200, "value": "old"})
        # Recent entry (5 minutes ago)
        store._history.append({"_timestamp": now - 300, "value": "recent"})

        result = store.get_history(minutes=60)
        assert len(result) == 1
        assert result[0]["value"] == "recent"

    def test_returns_all_within_window(self):
        store = MetricsStore()
        now = time.time()
        store._history.append({"_timestamp": now - 30, "value": "a"})
        store._history.append({"_timestamp": now - 10, "value": "b"})

        result = store.get_history(minutes=1)
        assert len(result) == 2


class TestGetLatest:
    def test_empty_store_returns_none(self):
        store = MetricsStore()
        assert store.get_latest() is None

    def test_returns_last_entry(self):
        store = MetricsStore()
        store._history.append({"_timestamp": 1, "value": "first"})
        store._history.append({"_timestamp": 2, "value": "second"})
        assert store.get_latest()["value"] == "second"


class TestTakeSnapshot:
    def test_snapshot_appends_to_history(self):
        store = MetricsStore()
        mock_overview = {
            "total_requests": 42,
            "total_errors": 1,
            "error_rate_percent": 2.4,
            "avg_latency_ms": 15.0,
            "latency_percentiles": {"p50_ms": 10, "p90_ms": 20, "p99_ms": 50},
            "active_services": 3,
            "healthy_services": 3,
        }
        with patch("app.core.telemetry.telemetry") as mock_telemetry:
            mock_telemetry.get_overview_stats.return_value = mock_overview
            store._take_snapshot()

        assert len(store._history) == 1
        snap = store._history[0]
        assert snap["request_count"] == 42
        assert snap["error_count"] == 1
        assert snap["p99_ms"] == 50
        assert "_timestamp" in snap

    def test_snapshot_respects_max_history(self):
        store = MetricsStore(max_history=2)
        mock_overview = {"latency_percentiles": {}}
        with patch("app.core.telemetry.telemetry") as mock_telemetry:
            mock_telemetry.get_overview_stats.return_value = mock_overview
            store._take_snapshot()
            store._take_snapshot()
            store._take_snapshot()

        assert len(store._history) == 2


class TestHistoryFiltering:
    def test_large_window_returns_everything(self):
        store = MetricsStore()
        now = time.time()
        for i in range(5):
            store._history.append({"_timestamp": now - i * 60, "i": i})
        assert len(store.get_history(minutes=9999)) == 5

    def test_zero_minute_window_returns_only_current_second(self):
        store = MetricsStore()
        now = time.time()
        store._history.append({"_timestamp": now - 120, "old": True})
        store._history.append({"_timestamp": now, "new": True})
        result = store.get_history(minutes=0)
        # Only the entry at exactly now (within float precision)
        assert all(s.get("_timestamp", 0) >= now for s in result)


class TestGetMetricsStoreSingleton:
    def test_returns_instance(self):
        import app.core.metrics_store as mod

        original = mod._store
        try:
            mod._store = None
            store = get_metrics_store()
            assert isinstance(store, MetricsStore)
        finally:
            mod._store = original

    def test_returns_same_instance(self):
        import app.core.metrics_store as mod

        original = mod._store
        try:
            mod._store = None
            a = get_metrics_store()
            b = get_metrics_store()
            assert a is b
        finally:
            mod._store = original
