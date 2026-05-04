"""
Reporter Agent - Generates assessment reports.

Responsible for:
- Analyzing mission findings
- Generating structured reports
- Providing remediation recommendations
- Supporting multiple report formats (HTML, JSON, Markdown)
"""

import logging
from typing import ClassVar

from pydantic import BaseModel, Field

from spectra_ai.prompts import REPORTING_PROMPT
from spectra_ai.sanitizer import sanitize_for_prompt
from spectra_platform.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from spectra_platform.services.ai.agents.registry import register_agent
from spectra_platform.services.ai.context import ContextManager, ContextSection, Priority

logger = logging.getLogger(__name__)


# --- Input/Output Models ---


class ReporterInput(BaseModel):
    """Input for the Reporter Agent."""

    findings: list[dict] = Field(..., description="All findings from the assessment")
    mission_summary: str = Field(..., description="Summary of the mission")
    target: str = Field(..., description="Target that was assessed")


class ReportSection(BaseModel):
    """A section of the report."""

    title: str
    content: str
    severity: str | None = None  # For vulnerability sections


class ReportOutput(AgentAction):
    """Generated report output."""

    action_type: str = "report_generated"
    executive_summary: str = Field(..., description="High-level summary")
    sections: list[ReportSection] = Field(default_factory=list)

    # Statistics
    critical_count: int = Field(0)
    high_count: int = Field(0)
    medium_count: int = Field(0)
    low_count: int = Field(0)
    info_count: int = Field(0)

    # Metadata
    assessment_date: str = Field(..., description="Date of assessment")
    target: str = Field(..., description="Target assessed")

    # Report file path when saved
    report_path: str | None = Field(None, description="Path to saved report file")


# --- Reporter Agent ---


@register_agent
class ReporterAgent(Agent[ReporterInput, ReportOutput]):
    """
    Reporter Agent generates comprehensive assessment reports.

    Capabilities:
    - Analyzes findings and calculates risk scores
    - Groups findings by severity and category
    - Provides actionable remediation steps
    - Generates executive summaries for management
    - Saves reports to disk in multiple formats
    """

    role: ClassVar[AgentRole] = AgentRole.REPORTER
    name: ClassVar[str] = "ReporterAgent"
    description: ClassVar[str] = "Generates structured security assessment reports"

    async def execute(
        self,
        context: AgentContext,
        input_data: ReporterInput,
    ) -> AgentResult:
        """Generate a comprehensive report from mission findings."""
        try:
            # Count findings by severity
            severity_counts = self._count_by_severity(input_data.findings)

            # Generate executive summary
            exec_summary = await self._generate_executive_summary(context, input_data, severity_counts)

            # Generate detailed sections
            sections = self._generate_sections(input_data.findings)

            # Create report output
            report = ReportOutput(
                confidence=1.0,
                risk_level=self._calculate_overall_risk(severity_counts),
                reasoning="Report generated from mission findings",
                executive_summary=exec_summary,
                sections=sections,
                critical_count=severity_counts.get("critical", 0),
                high_count=severity_counts.get("high", 0),
                medium_count=severity_counts.get("medium", 0),
                low_count=severity_counts.get("low", 0),
                info_count=severity_counts.get("info", 0),
                assessment_date=context.session_id or context.mission_id,
                target=input_data.target,
            )

            # Save report to disk
            report_path = await self._save_report(context.mission_id, report, input_data)
            report.report_path = report_path

            return AgentResult(
                success=True,
                action=report,
            )

        except Exception as e:
            logger.exception("Report generation failed for mission %s: %s", context.mission_id, e)
            return AgentResult(
                success=False,
                error=str(e),
            )

    def _count_by_severity(self, findings: list[dict]) -> dict[str, int]:
        """Count findings by severity level."""
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

        for finding in findings:
            severity = finding.get("severity", "info").lower()
            if severity in counts:
                counts[severity] += 1

        return counts

    def _calculate_overall_risk(self, severity_counts: dict[str, int]) -> ActionRisk:
        """Calculate overall risk level from severity counts."""
        if severity_counts.get("critical", 0) > 0:
            return ActionRisk.CRITICAL
        elif severity_counts.get("high", 0) > 2:
            return ActionRisk.HIGH
        elif severity_counts.get("high", 0) > 0:
            return ActionRisk.MEDIUM
        else:
            return ActionRisk.LOW

    async def _generate_executive_summary(
        self,
        context: AgentContext,
        input_data: ReporterInput,
        severity_counts: dict[str, int],
    ) -> str:
        """Generate an executive summary of the assessment."""
        total_findings = sum(severity_counts.values())

        findings_summary = f"""Total Findings: {total_findings}
- Critical: {severity_counts.get("critical", 0)}
- High: {severity_counts.get("high", 0)}
- Medium: {severity_counts.get("medium", 0)}
- Low: {severity_counts.get("low", 0)}
- Informational: {severity_counts.get("info", 0)}"""

        base_prompt = REPORTING_PROMPT.format(
            target=sanitize_for_prompt(input_data.target, field_name="target"),
            date=context.session_id or context.mission_id,
            mission_summary="{mission_summary}",
            findings_summary="{findings_summary}",
        )

        ctx = ContextManager(max_context_tokens=4000)
        prompt = ctx.build(
            [
                ContextSection("task", base_prompt, Priority.CRITICAL),
                ContextSection(
                    "mission_summary", f"Mission Summary: {sanitize_for_prompt(input_data.mission_summary, field_name='mission_summary')}", Priority.HIGH, max_tokens=800
                ),
                ContextSection(
                    "findings_summary", f"Findings Summary:\n{sanitize_for_prompt(findings_summary, field_name='findings_summary')}", Priority.HIGH, max_tokens=600
                ),
            ]
        )

        system_prompt = self._build_system_prompt(context)

        try:
            # Use LLM to generate summary
            response = await self._llm_generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.3,
            )
            return response.content.strip()
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.warning("LLM summary generation failed, using fallback: %s", e)
            # Fallback to template
            return f"""
Security Assessment Summary for {input_data.target}

Mission: {input_data.mission_summary}

{findings_summary}

The assessment identified {"significant security concerns" if severity_counts.get("critical", 0) > 0 else "areas for improvement"}.
Immediate attention is required for critical and high severity findings.
""".strip()

    def _generate_sections(self, findings: list[dict]) -> list[ReportSection]:
        """Generate report sections from findings."""
        sections = []

        # Group findings by severity
        # Group findings by severity
        by_severity = {}
        verified_exploits = []

        for finding in findings:
            # Check if this is a verified exploit
            if finding.get("source") == "exploitation" or finding.get("confirmed"):
                verified_exploits.append(finding)
                continue  # Skip adding to general severity groups to avoid duplication, OR keep it.
                # Let's keep it in severity groups too, but have a dedicated section at the top.

            severity = finding.get("severity", "info").lower()
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(finding)

        # Create sections

        # 1. Verified Exploits (Top Priority)
        if verified_exploits:
            content = "\n\n".join(
                [
                    f"### {f.get('title', 'Exploit')}\n"
                    f"**Proof:** {f.get('proof', f.get('description', 'No proofs provided'))}\n"
                    f"**Vector:** {f.get('tool_name', 'Unknown')}"
                    for f in verified_exploits
                ]
            )
            sections.append(
                ReportSection(
                    title="Verified Exploits (Proof of Concept)",
                    content=content,
                    severity="critical",
                )
            )

        # Create sections for each severity level
        severity_order = ["critical", "high", "medium", "low", "info"]

        for severity in severity_order:
            if by_severity.get(severity):
                items = by_severity[severity]
                content = "\n\n".join(self._format_finding(f) for f in items)

                sections.append(
                    ReportSection(
                        title=f"{severity.capitalize()} Severity Findings",
                        content=content,
                        severity=severity,
                    )
                )

        # Add recommendations section
        sections.append(
            ReportSection(
                title="Recommendations",
                content="1. Address critical findings immediately\n2. Implement security best practices\n3. Conduct regular assessments",
            )
        )

        return sections

    def _format_finding(self, f: dict) -> str:
        """Format a single finding for the report, handling various finding schemas."""
        # Try structured title/description first
        title = f.get("title") or f.get("name") or f.get("template-id")
        desc = f.get("description")

        # Service/port findings (nmap-style)
        port = f.get("port") or f.get("portid")
        ip = f.get("ip") or f.get("host")
        product = f.get("product")
        version = f.get("version")
        service = f.get("service") or f.get("name")

        if port and ip:
            svc = f"{service}" if service else "unknown"
            prod = f"{product} {version}".strip() if product else ""
            line = f"- **{ip}:{port}** ({svc})"
            if prod:
                line += f" — {prod}"
            if desc:
                line += f"\n  {desc}"
            return line

        # URL-based findings (web scanners)
        url = f.get("url") or f.get("matched-at")
        if url:
            line = f"- **{url}**"
            if title:
                line += f": {title}"
            if desc:
                line += f"\n  {desc}"
            return line

        # Generic finding with title
        if title:
            line = f"- **{title}**"
            if desc:
                line += f": {desc}"
            return line

        # Fallback: dump key-value pairs
        parts = []
        for k, v in f.items():
            if v and k not in ("severity", "source", "confirmed", "mitre_techniques", "count"):
                parts.append(f"{k}: {v}")
        return "- " + ", ".join(parts) if parts else "- (no details)"

    async def _save_report(self, mission_id: str, report: ReportOutput, input_data: ReporterInput) -> str:
        """Save report to storage in multiple formats."""
        import json
        from datetime import UTC, datetime

        from spectra_platform.core.config import settings
        from spectra_platform.services.storage import get_storage_service

        storage = get_storage_service()
        bucket = settings.S3_BUCKET_MISSIONS
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        base_name = f"report_{timestamp}"

        # Save JSON format
        report_data = {
            "mission_id": mission_id,
            "target": report.target,
            "assessment_date": report.assessment_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "executive_summary": report.executive_summary,
            "statistics": {
                "critical": report.critical_count,
                "high": report.high_count,
                "medium": report.medium_count,
                "low": report.low_count,
                "info": report.info_count,
                "total": report.critical_count
                + report.high_count
                + report.medium_count
                + report.low_count
                + report.info_count,
            },
            "sections": [s.model_dump() for s in report.sections],
            "findings": input_data.findings,
        }

        json_bytes = json.dumps(report_data, indent=2, default=str).encode()
        await storage.upload(bucket, f"{mission_id}/reports/{base_name}.json", json_bytes)

        # Save Markdown format
        md_content = self._generate_markdown_report(report, input_data)
        md_key = f"{mission_id}/reports/{base_name}.md"
        await storage.upload(bucket, md_key, md_content.encode())

        # Save HTML format
        html_content = self._generate_html_report(report, input_data)
        await storage.upload(bucket, f"{mission_id}/reports/{base_name}.html", html_content.encode())

        logger.info("Reports saved to storage: %s/%s/reports/", bucket, mission_id)
        return md_key

    def _generate_markdown_report(self, report: ReportOutput, input_data: ReporterInput) -> str:
        """Generate markdown formatted report."""
        from datetime import UTC, datetime

        md = f"""# Security Assessment Report

## Target: {report.target}
**Date:** {datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}

---

## Executive Summary

{report.executive_summary}

---

## Findings Summary

| Severity | Count |
|----------|-------|
| Critical | {report.critical_count} |
| High | {report.high_count} |
| Medium | {report.medium_count} |
| Low | {report.low_count} |
| Info | {report.info_count} |
| **Total** | **{report.critical_count + report.high_count + report.medium_count + report.low_count + report.info_count}** |

---

"""
        for section in report.sections:
            severity_badge = f" [{section.severity.upper()}]" if section.severity else ""
            md += f"## {section.title}{severity_badge}\n\n{section.content}\n\n---\n\n"

        return md

    def _generate_html_report(self, report: ReportOutput, input_data: ReporterInput) -> str:
        """Generate HTML formatted report."""
        from datetime import UTC, datetime

        sections_html = ""
        for section in report.sections:
            severity_class = f"severity-{section.severity}" if section.severity else ""
            content_html = section.content.replace("\n", "<br>")
            sections_html += f"""
            <div class="section {severity_class}">
                <h2>{section.title}</h2>
                <p>{content_html}</p>
            </div>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Assessment Report - {report.target}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f172a; color: #e2e8f0; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #38bdf8; border-bottom: 2px solid #38bdf8; padding-bottom: 10px; }}
        h2 {{ color: #94a3b8; margin-top: 30px; }}
        .summary {{ background: #1e293b; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat {{ background: #1e293b; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; }}
        .stat-critical {{ color: #ef4444; }}
        .stat-high {{ color: #f97316; }}
        .stat-medium {{ color: #eab308; }}
        .stat-low {{ color: #22c55e; }}
        .stat-info {{ color: #3b82f6; }}
        .section {{ background: #1e293b; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .severity-critical {{ border-left: 4px solid #ef4444; }}
        .severity-high {{ border-left: 4px solid #f97316; }}
        .severity-medium {{ border-left: 4px solid #eab308; }}
        .severity-low {{ border-left: 4px solid #22c55e; }}
        .severity-info {{ border-left: 4px solid #3b82f6; }}
        pre {{ background: #0f172a; padding: 15px; border-radius: 4px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Security Assessment Report</h1>
        <p><strong>Target:</strong> {report.target}</p>
        <p><strong>Date:</strong> {datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}</p>

        <div class="summary">
            <h2>Executive Summary</h2>
            <p>{report.executive_summary.replace(chr(10), "<br>")}</p>
        </div>

        <h2>Findings Overview</h2>
        <div class="stats">
            <div class="stat"><div class="stat-value stat-critical">{report.critical_count}</div><div>Critical</div></div>
            <div class="stat"><div class="stat-value stat-high">{report.high_count}</div><div>High</div></div>
            <div class="stat"><div class="stat-value stat-medium">{report.medium_count}</div><div>Medium</div></div>
            <div class="stat"><div class="stat-value stat-low">{report.low_count}</div><div>Low</div></div>
            <div class="stat"><div class="stat-value stat-info">{report.info_count}</div><div>Info</div></div>
        </div>

        {sections_html}
    </div>
</body>
</html>"""
        return html
