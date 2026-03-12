"""Background report generation tasks."""

from __future__ import annotations

import logging

from sqlalchemy import select

logger = logging.getLogger("spectra.worker.reports")


async def generate_mission_report(mission_id: str, report_format: str = "pdf") -> str:
    """Generate a mission report in the background.

    Returns the path/URL where the report was saved.
    """
    from app.core.database import async_session_maker
    from app.models.finding import Finding
    from app.models.mission import Mission
    from app.services.ai.agents.base import AgentContext
    from app.services.ai.agents.reporter import ReporterAgent, ReporterInput
    from app.services.ai.llm import get_global_llm_client

    async with async_session_maker() as session:
        mission_result = await session.execute(select(Mission).where(Mission.id == mission_id))
        mission = mission_result.scalar_one_or_none()
        if not mission:
            raise ValueError(f"Mission {mission_id} not found")

        findings_result = await session.execute(select(Finding).where(Finding.mission_id == mission_id))
        findings = [
            {
                "title": getattr(f, "title", ""),
                "severity": getattr(f, "severity", "info"),
                "description": getattr(f, "description", ""),
                "source": getattr(f, "source", ""),
                "confirmed": getattr(f, "confirmed", False),
                "tool_name": getattr(f, "tool_name", ""),
            }
            for f in findings_result.scalars().all()
        ]

    target = getattr(mission, "target", "unknown")
    directive = getattr(mission, "directive", "")

    llm = await get_global_llm_client()
    reporter = ReporterAgent(llm=llm)
    context = AgentContext(mission_id=mission_id)
    input_data = ReporterInput(
        findings=findings,
        mission_summary=directive,
        target=target,
    )

    result = await reporter.execute(context, input_data)
    if not result.success:
        raise RuntimeError(f"Report generation failed: {result.error}")

    report_path = result.action.report_path if result.action else ""
    logger.info("Generated %s report for mission %s: %s", report_format, mission_id, report_path)
    return report_path or ""


async def generate_executive_summary(mission_id: str) -> str:
    """Generate an executive summary for a mission."""
    from app.core.database import async_session_maker
    from app.models.finding import Finding
    from app.models.mission import Mission
    from app.services.ai.agents.base import AgentContext
    from app.services.ai.agents.reporter import ReporterAgent, ReporterInput
    from app.services.ai.llm import get_global_llm_client

    async with async_session_maker() as session:
        mission_result = await session.execute(select(Mission).where(Mission.id == mission_id))
        mission = mission_result.scalar_one_or_none()
        if not mission:
            raise ValueError(f"Mission {mission_id} not found")

        findings_result = await session.execute(select(Finding).where(Finding.mission_id == mission_id))
        findings = [
            {
                "title": getattr(f, "title", ""),
                "severity": getattr(f, "severity", "info"),
                "description": getattr(f, "description", ""),
            }
            for f in findings_result.scalars().all()
        ]

    target = getattr(mission, "target", "unknown")
    directive = getattr(mission, "directive", "")

    llm = await get_global_llm_client()
    reporter = ReporterAgent(llm=llm)
    context = AgentContext(mission_id=mission_id)
    input_data = ReporterInput(
        findings=findings,
        mission_summary=directive,
        target=target,
    )

    result = await reporter.execute(context, input_data)
    if not result.success:
        raise RuntimeError(f"Executive summary failed: {result.error}")

    summary = result.action.executive_summary if result.action else ""
    logger.info("Generated executive summary for mission %s", mission_id)
    return summary
