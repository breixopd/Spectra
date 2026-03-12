from unittest.mock import AsyncMock

import pytest

from app.services.ai.agents.base import ActionRisk, AgentContext
from app.services.ai.agents.reporter import ReporterAgent, ReporterInput, ReportOutput


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate.return_value = "Executive Summary Content"
    return llm


@pytest.fixture
def reporter_agent(mock_llm):
    return ReporterAgent(mock_llm)


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

    result = await reporter_agent.execute(context, input_data)

    assert result.success
    assert isinstance(result.action, ReportOutput)
    assert result.action.critical_count == 1
    assert result.action.low_count == 1
    assert result.action.risk_level == ActionRisk.CRITICAL
    assert result.action.executive_summary == "Executive Summary Content"
    assert len(result.action.sections) > 0


@pytest.mark.asyncio
async def test_reporter_risk_calculation(reporter_agent):
    # Critical risk
    assert reporter_agent._calculate_overall_risk({"critical": 1}) == ActionRisk.CRITICAL

    # High risk (>2 high)
    assert reporter_agent._calculate_overall_risk({"high": 3}) == ActionRisk.HIGH

    # Medium risk (1-2 high)
    assert reporter_agent._calculate_overall_risk({"high": 1}) == ActionRisk.MEDIUM

    # Low risk
    assert reporter_agent._calculate_overall_risk({"medium": 5}) == ActionRisk.LOW


@pytest.mark.asyncio
async def test_reporter_llm_failure_fallback(reporter_agent, context):
    # Simulate LLM failure
    reporter_agent.llm.generate.side_effect = Exception("LLM Error")

    input_data = ReporterInput(findings=[], mission_summary="Mission summary", target="example.com")

    result = await reporter_agent.execute(context, input_data)

    assert result.success
    # Should fall back to template
    assert "Security Assessment Summary" in result.action.executive_summary
