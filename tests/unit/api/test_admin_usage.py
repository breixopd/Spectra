"""Tests for the /admin/usage endpoint — token/cost aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spectra_ai.cost_tracker import CostTracker


def _build_mock_tracker(mission_id: str, agent_records: list[dict]) -> CostTracker:
    """Create a real CostTracker and feed it recorded calls."""
    tracker = CostTracker(mission_id)
    for rec in agent_records:
        tracker.record(
            agent_name=rec["agent"],
            agent_role=rec["role"],
            model=rec.get("model", "gpt-4o-mini"),
            usage={
                "prompt_tokens": rec.get("prompt", 100),
                "completion_tokens": rec.get("completion", 50),
            },
            latency_ms=rec.get("latency", 120.0),
            error=rec.get("error", False),
        )
    return tracker


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("spectra_ai.cost_tracker.get_cost_trackers")
@patch("app.api.routers.admin.audit.telemetry")
async def test_admin_usage_response_format(mock_telemetry, mock_get_trackers):
    """The endpoint must return the documented top-level keys."""
    mock_telemetry.get_saas_metrics.return_value = {"missions": {"started": 2}}

    tracker = _build_mock_tracker(
        "m-1",
        [
            {"agent": "planner", "role": "planner", "prompt": 200, "completion": 100},
        ],
    )
    mock_get_trackers.return_value = {"m-1": tracker}

    from app.api.routers.admin.audit import admin_usage

    # Call the endpoint function directly (bypass auth via mock)
    with patch("app.api.routers.admin.audit.require_permission", return_value=MagicMock()):
        result = await admin_usage(request=MagicMock(), _user=MagicMock())

    assert "total_calls" in result
    assert "total_tokens" in result
    assert "total_cost_usd" in result
    assert "active_missions" in result
    assert "by_agent" in result
    assert isinstance(result["by_agent"], list)


# ---------------------------------------------------------------------------
# Token / cost aggregation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("spectra_ai.cost_tracker.get_cost_trackers")
@patch("app.api.routers.admin.audit.telemetry")
async def test_admin_usage_token_cost_aggregation(mock_telemetry, mock_get_trackers):
    """Totals must aggregate across all trackers and agents."""
    mock_telemetry.get_saas_metrics.return_value = {"missions": {"started": 3}}

    t1 = _build_mock_tracker(
        "m-1",
        [
            {"agent": "planner", "role": "planner", "prompt": 200, "completion": 100},
            {"agent": "executor", "role": "executor", "prompt": 300, "completion": 150},
        ],
    )
    t2 = _build_mock_tracker(
        "m-2",
        [
            {"agent": "planner", "role": "planner", "prompt": 400, "completion": 200},
        ],
    )
    mock_get_trackers.return_value = {"m-1": t1, "m-2": t2}

    from app.api.routers.admin.audit import admin_usage

    with patch("app.api.routers.admin.audit.require_permission", return_value=MagicMock()):
        result = await admin_usage(request=MagicMock(), _user=MagicMock())

    # 3 calls total (2 in t1, 1 in t2)
    assert result["total_calls"] == 3
    # Tokens: (200+100) + (300+150) + (400+200) = 1350
    assert result["total_tokens"] == 1350
    assert result["total_cost_usd"] > 0
    assert result["active_missions"] == 3
    # 3 agent-level rows (planner+executor from m-1, planner from m-2)
    assert len(result["by_agent"]) == 3

    # Verify each row has required fields
    for row in result["by_agent"]:
        assert "mission_id" in row
        assert "agent_name" in row
        assert "tokens" in row
        assert "cost_usd" in row


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("spectra_ai.cost_tracker.get_cost_trackers")
@patch("app.api.routers.admin.audit.telemetry")
async def test_admin_usage_empty_state(mock_telemetry, mock_get_trackers):
    """With no active trackers, everything should be zero."""
    mock_telemetry.get_saas_metrics.return_value = {"missions": {"started": 0}}
    mock_get_trackers.return_value = {}

    from app.api.routers.admin.audit import admin_usage

    with patch("app.api.routers.admin.audit.require_permission", return_value=MagicMock()):
        result = await admin_usage(request=MagicMock(), _user=MagicMock())

    assert result["total_calls"] == 0
    assert result["total_tokens"] == 0
    assert result["total_cost_usd"] == 0.0
    assert result["by_agent"] == []
