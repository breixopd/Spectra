"""
HTML Report Generation for Spectra missions.

Generates self-contained HTML reports from mission data using inline
Jinja2 templates. Reports include dark-themed CSS, severity charts,
findings tables, and MITRE ATT&CK mapping — all without external
dependencies so they work offline / air-gapped.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

logger = logging.getLogger("spectra.mission.report")

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITY_COLORS = {
    "critical": "#e74c3c",
    "high": "#e67e22",
    "medium": "#f1c40f",
    "low": "#3498db",
    "info": "#95a5a6",
}

_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spectra Report — {{ mission.get("name", mission.get("id", "Unknown")) }}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;
       background:#0d1117;color:#c9d1d9;line-height:1.6;padding:2rem}
  .container{max-width:960px;margin:0 auto}
  h1{color:#58a6ff;font-size:1.8rem;border-bottom:1px solid #21262d;padding-bottom:.5rem;margin-bottom:1rem}
  h2{color:#79c0ff;font-size:1.3rem;margin-top:2rem;margin-bottom:.8rem}
  h3{color:#d2a8ff;font-size:1.1rem;margin-top:1.2rem;margin-bottom:.5rem}
  .meta{color:#8b949e;font-size:.85rem;margin-bottom:1.5rem}
  .summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem}
  .stat-card{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:1rem;text-align:center}
  .stat-card .value{font-size:1.8rem;font-weight:700;color:#58a6ff}
  .stat-card .label{font-size:.75rem;color:#8b949e;text-transform:uppercase;letter-spacing:.05em}
  .chart{margin:1rem 0}
  .bar-row{display:flex;align-items:center;margin:.35rem 0}
  .bar-label{width:70px;font-size:.8rem;text-transform:capitalize;color:#8b949e}
  .bar-track{flex:1;background:#161b22;border-radius:3px;height:22px;overflow:hidden}
  .bar-fill{height:100%;border-radius:3px;display:flex;align-items:center;padding-left:8px;font-size:.75rem;
            color:#fff;font-weight:600;min-width:fit-content;transition:width .3s}
  table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.85rem}
  th{background:#161b22;color:#79c0ff;text-align:left;padding:.6rem .8rem;border-bottom:2px solid #21262d}
  td{padding:.6rem .8rem;border-bottom:1px solid #21262d}
  tr:hover{background:#161b2280}
  .severity{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.75rem;font-weight:600;color:#fff;text-transform:uppercase}
  .sev-critical{background:#e74c3c}
  .sev-high{background:#e67e22}
  .sev-medium{background:#f1c40f;color:#000}
  .sev-low{background:#3498db}
  .sev-info{background:#95a5a6}
  .tag{display:inline-block;background:#1f6feb33;color:#58a6ff;padding:2px 8px;border-radius:3px;font-size:.75rem;margin:2px}
  .section{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:1.2rem;margin-bottom:1.5rem}
  .footer{margin-top:3rem;padding-top:1rem;border-top:1px solid #21262d;font-size:.75rem;color:#484f58;text-align:center}
  ul{margin:.5rem 0 .5rem 1.5rem}
  li{margin:.25rem 0}
</style>
</head>
<body>
<div class="container">
  <h1>{{ mission.get("name", "Security Assessment Report") }}</h1>
  <div class="meta">
    Mission ID: {{ mission.get("id", "N/A") }} &middot;
    Target: {{ mission.get("target", "N/A") }} &middot;
    Generated: {{ generated_at }}
  </div>

  <!-- Executive Summary -->
  <h2>Executive Summary</h2>
  <div class="section">
    <div class="summary-grid">
      <div class="stat-card"><div class="value">{{ total_findings }}</div><div class="label">Total Findings</div></div>
      <div class="stat-card"><div class="value" style="color:#e74c3c">{{ severity_counts.get("critical", 0) }}</div><div class="label">Critical</div></div>
      <div class="stat-card"><div class="value" style="color:#e67e22">{{ severity_counts.get("high", 0) }}</div><div class="label">High</div></div>
      <div class="stat-card"><div class="value" style="color:#f1c40f">{{ severity_counts.get("medium", 0) }}</div><div class="label">Medium</div></div>
      <div class="stat-card"><div class="value" style="color:#3498db">{{ severity_counts.get("low", 0) }}</div><div class="label">Low</div></div>
    </div>
    {% if mission.get("directive") %}
    <p><strong>Directive:</strong> {{ mission["directive"] }}</p>
    {% endif %}
    {% if mission.get("summary") %}
    <p>{{ mission["summary"] }}</p>
    {% endif %}
  </div>

  <!-- Severity Chart -->
  {% if total_findings > 0 %}
  <h2>Finding Severity Distribution</h2>
  <div class="section chart">
    {% for sev in ["critical","high","medium","low","info"] %}
    {% set count = severity_counts.get(sev, 0) %}
    {% if count > 0 %}
    <div class="bar-row">
      <div class="bar-label">{{ sev }}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:{{ (count / max_severity * 100) | round(1) }}%;background:{{ severity_colors[sev] }}">{{ count }}</div>
      </div>
    </div>
    {% endif %}
    {% endfor %}
  </div>
  {% endif %}

  <!-- Findings Table -->
  {% if findings %}
  <h2>Findings</h2>
  <div class="section" style="overflow-x:auto">
    <table>
      <thead><tr><th>#</th><th>Title</th><th>Severity</th><th>Type</th><th>Details</th></tr></thead>
      <tbody>
      {% for f in findings %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ f.get("title", f.get("name", "Untitled")) }}</td>
        <td><span class="severity sev-{{ f.get('severity', 'info') | lower }}">{{ f.get("severity", "info") }}</span></td>
        <td>{{ f.get("type", "—") }}</td>
        <td>{{ f.get("description", f.get("details", "—")) }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <!-- Attack Surface -->
  {% if attack_surface %}
  <h2>Attack Surface Summary</h2>
  <div class="section">
    {% if attack_surface.get("services") %}
    <h3>Discovered Services</h3>
    <table>
      <thead><tr><th>Port</th><th>Service</th><th>Product</th><th>Version</th></tr></thead>
      <tbody>
      {% for s in attack_surface["services"] %}
      <tr>
        <td>{{ s.get("port", "—") }}</td>
        <td>{{ s.get("service", "—") }}</td>
        <td>{{ s.get("product", "—") }}</td>
        <td>{{ s.get("version", "—") }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% endif %}
    {% if attack_surface.get("technologies") %}
    <h3>Technologies</h3>
    <p>{% for t in attack_surface["technologies"] %}<span class="tag">{{ t }}</span>{% endfor %}</p>
    {% endif %}
    {% if attack_surface.get("os") %}
    <h3>Operating System</h3>
    <p>{{ attack_surface["os"] }}</p>
    {% endif %}
  </div>
  {% endif %}

  <!-- Tools Used & Timeline -->
  {% if tools_used %}
  <h2>Tools Used</h2>
  <div class="section">
    <p>{% for t in tools_used %}<span class="tag">{{ t }}</span>{% endfor %}</p>
  </div>
  {% endif %}

  {% if timeline %}
  <h2>Timeline</h2>
  <div class="section">
    <table>
      <thead><tr><th>Time</th><th>Phase</th><th>Event</th></tr></thead>
      <tbody>
      {% for ev in timeline %}
      <tr>
        <td>{{ ev.get("time", "—") }}</td>
        <td>{{ ev.get("phase", "—") }}</td>
        <td>{{ ev.get("event", ev.get("description", "—")) }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <!-- MITRE ATT&CK -->
  {% if mitre_techniques %}
  <h2>MITRE ATT&CK Techniques</h2>
  <div class="section">
    <table>
      <thead><tr><th>ID</th><th>Name</th><th>Tactic</th></tr></thead>
      <tbody>
      {% for t in mitre_techniques %}
      <tr>
        <td>{{ t.get("id", "—") }}</td>
        <td>{{ t.get("name", "—") }}</td>
        <td>{{ t.get("tactic", "—") }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <div class="footer">
    Generated by Spectra &mdash; Autonomous AI Security Assessment Platform &mdash; {{ generated_at }}
  </div>
</div>
</body>
</html>
"""

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)


def _count_severities(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "info").lower()
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda f: SEVERITY_ORDER.get(f.get("severity", "info").lower(), 99),
    )


def generate_html_report(mission_data: dict) -> str:
    """
    Produce a self-contained HTML report from structured mission data.

    Expected keys in *mission_data*:
        - mission  (dict): id, name, target, directive, summary
        - findings (list[dict]): title/name, severity, type, description
        - attack_surface (dict, optional): services, technologies, os
        - tools_used (list[str], optional)
        - timeline (list[dict], optional): time, phase, event
        - mitre_techniques (list[dict], optional): id, name, tactic
    """
    mission = mission_data.get("mission", {})
    findings = _sort_findings(mission_data.get("findings", []))
    severity_counts = _count_severities(findings)
    max_severity = max(severity_counts.values()) if severity_counts else 1

    template = _jinja_env.from_string(_REPORT_TEMPLATE)
    return template.render(
        mission=mission,
        findings=findings,
        total_findings=len(findings),
        severity_counts=severity_counts,
        max_severity=max_severity,
        severity_colors=SEVERITY_COLORS,
        attack_surface=mission_data.get("attack_surface"),
        tools_used=mission_data.get("tools_used", []),
        timeline=mission_data.get("timeline", []),
        mitre_techniques=mission_data.get("mitre_techniques", []),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def save_report(mission_id: str, html_content: str) -> str:
    """
    Persist an HTML report to disk (encrypted at rest).

    Returns the absolute path of the saved file.
    """
    from app.core.encryption import encrypt_file

    report_dir = os.path.join("reports", "missions", mission_id)
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    encrypt_file(Path(path))
    logger.info("Report saved (encrypted) → %s", path)
    return path


def generate_pdf_report(mission_data: dict) -> bytes | None:
    """Generate a PDF report from mission data.

    Uses xhtml2pdf to convert the HTML report to PDF.
    Returns PDF bytes or None on failure.
    """
    try:
        from io import BytesIO

        from xhtml2pdf import pisa

        html = generate_html_report(mission_data)
        pdf_buffer = BytesIO()

        pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

        if pisa_status.err:
            logger.error("PDF generation failed: %d errors", pisa_status.err)
            return None

        return pdf_buffer.getvalue()
    except ImportError:
        logger.warning("xhtml2pdf not installed, PDF export unavailable")
        return None
    except Exception as e:
        logger.error("PDF generation error: %s", e)
        return None


def save_pdf_report(mission_id: str, pdf_bytes: bytes) -> str | None:
    """Save PDF report to disk (encrypted at rest)."""
    from app.core.encryption import encrypt_file

    output_dir = Path("reports/missions") / mission_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    try:
        output_path.write_bytes(pdf_bytes)
        encrypt_file(output_path)
        return str(output_path)
    except Exception as e:
        logger.error("Failed to save PDF: %s", e)
        return None
