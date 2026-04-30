"""Tests for report generation worker tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_session_ctx(session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_mission(mission_id="m-1", target="10.0.0.1", directive="Full scan", summary=None):
    m = MagicMock()
    m.id = mission_id
    m.target = target
    m.directive = directive
    m.summary = summary
    return m


# --- generate_mission_report ---


@pytest.mark.asyncio
async def test_generate_mission_report_returns_path():
    from spectra_worker.report_jobs import generate_mission_report

    mission = _mock_mission(
        summary={
            "findings": [
                {
                    "title": "XSS",
                    "severity": "high",
                    "description": "Reflected XSS",
                    "tool_source": "nuclei",
                    "confirmed": True,
                }
            ]
        }
    )

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = mission

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    mock_action = MagicMock()
    mock_action.report_path = "/reports/m-1.pdf"
    mock_action.executive_summary = "Summary"
    mock_agent_result = MagicMock()
    mock_agent_result.success = True
    mock_agent_result.action = mock_action

    mock_reporter = AsyncMock()
    mock_reporter.execute = AsyncMock(return_value=mock_agent_result)

    with (
        patch("app.core.database.async_session_maker", return_value=_mock_session_ctx(session)),
        patch("spectra_ai.llm.get_global_llm_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("app.services.ai.agents.reporter.ReporterAgent", return_value=mock_reporter),
    ):
        path = await generate_mission_report("m-1")

    assert path == "/reports/m-1.pdf"
    mock_reporter.execute.assert_awaited_once()
    assert session.execute.await_count == 1
    reporter_input = mock_reporter.execute.await_args.args[1]
    assert reporter_input.findings == [
        {
            "title": "XSS",
            "severity": "high",
            "description": "Reflected XSS",
            "source": "nuclei",
            "confirmed": True,
            "tool_name": "nuclei",
        }
    ]


@pytest.mark.asyncio
async def test_generate_mission_report_handles_missing_mission():
    from spectra_worker.report_jobs import generate_mission_report

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    with (
        patch("app.core.database.async_session_maker", return_value=_mock_session_ctx(session)),
    ):
        with pytest.raises(ValueError, match="not found"):
            await generate_mission_report("nonexistent")


# --- generate_executive_summary ---


@pytest.mark.asyncio
async def test_generate_executive_summary_returns_text():
    from spectra_worker.report_jobs import generate_executive_summary

    mission = _mock_mission(
        summary={
            "findings": [
                {
                    "title": "XSS",
                    "severity": "high",
                    "description": "Reflected XSS",
                }
            ]
        }
    )

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = mission

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    mock_action = MagicMock()
    mock_action.executive_summary = "The assessment identified 1 high-severity finding."
    mock_agent_result = MagicMock()
    mock_agent_result.success = True
    mock_agent_result.action = mock_action

    mock_reporter = AsyncMock()
    mock_reporter.execute = AsyncMock(return_value=mock_agent_result)

    with (
        patch("app.core.database.async_session_maker", return_value=_mock_session_ctx(session)),
        patch("spectra_ai.llm.get_global_llm_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("app.services.ai.agents.reporter.ReporterAgent", return_value=mock_reporter),
    ):
        summary = await generate_executive_summary("m-1")

    assert "high-severity" in summary
    mock_reporter.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_executive_summary_missing_mission():
    from spectra_worker.report_jobs import generate_executive_summary

    mission_result = MagicMock()
    mission_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mission_result)

    with (
        patch("app.core.database.async_session_maker", return_value=_mock_session_ctx(session)),
    ):
        with pytest.raises(ValueError, match="not found"):
            await generate_executive_summary("nonexistent")
