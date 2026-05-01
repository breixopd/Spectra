from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai.llm import LLMResponse
from spectra_platform.services.ai.agents.base import ActionRisk, AgentContext
from spectra_platform.services.ai.agents.reporter import ReporterAgent, ReporterInput, ReportOutput


@pytest.fixture
def reporter_agent():
    return ReporterAgent(MagicMock())


@pytest.fixture
def context():
    return AgentContext(
        mission_id="test-mission-1",
        session_id="test-session",
        target="example.com",
        mission="Test Mission",
        phase="reporting",
    )


@pytest.mark.asyncio
async def test_reporter_execution(reporter_agent, context):
    input_data = ReporterInput(
        findings=[
            {
                "title": "Critical Vuln",
                "severity": "critical",
                "description": "Bad stuff",
            },
            {"title": "Low Vuln", "severity": "low", "description": "Minor stuff"},
        ],
        mission_summary="Mission completed successfully",
        target="example.com",
    )

    with (
        patch.object(
            reporter_agent,
            "_llm_generate",
            new=AsyncMock(return_value=LLMResponse(content="Executive Summary Content", model="test", provider="test")),
        ),
        patch.object(reporter_agent, "_save_report", new=AsyncMock(return_value="/tmp/report.md")),
    ):
        result = await reporter_agent.execute(context, input_data)

    assert result.success
    assert isinstance(result.action, ReportOutput)
    assert result.action.critical_count == 1
    assert result.action.low_count == 1
    assert result.action.risk_level == ActionRisk.CRITICAL
    assert result.action.executive_summary == "Executive Summary Content"
    assert len(result.action.sections) > 0
    assert result.action.report_path == "/tmp/report.md"


def test_reporter_risk_calculation(reporter_agent):
    assert reporter_agent._calculate_overall_risk({"critical": 1}) == ActionRisk.CRITICAL
    assert reporter_agent._calculate_overall_risk({"high": 3}) == ActionRisk.HIGH
    assert reporter_agent._calculate_overall_risk({"high": 1}) == ActionRisk.MEDIUM
    assert reporter_agent._calculate_overall_risk({"medium": 5}) == ActionRisk.LOW


@pytest.mark.asyncio
async def test_reporter_llm_failure_fallback(reporter_agent, context):
    input_data = ReporterInput(findings=[], mission_summary="Mission summary", target="example.com")

    with (
        patch.object(reporter_agent, "_llm_generate", new=AsyncMock(side_effect=RuntimeError("LLM Error"))),
        patch.object(reporter_agent, "_save_report", new=AsyncMock(return_value="/tmp/report.md")),
    ):
        result = await reporter_agent.execute(context, input_data)

    assert result.success
    assert "Security Assessment Summary" in result.action.executive_summary
