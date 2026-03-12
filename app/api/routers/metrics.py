"""Prometheus text exposition format endpoint for OTel collector compatibility."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.telemetry import telemetry

router = APIRouter()


def _prom_name(name: str) -> str:
    """Convert dotted OTel metric name to Prometheus-safe name."""
    return name.replace(".", "_").replace("-", "_")


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics",
    description="Export metrics in Prometheus text exposition format.",
)
async def prometheus_metrics() -> str:
    """Export metrics in Prometheus text format for OTel collector compatibility."""
    lines: list[str] = []
    seen: set[str] = set()

    for family in telemetry.get_all_metrics():
        prom = _prom_name(family.name)
        if prom not in seen:
            seen.add(prom)
            if family.description:
                lines.append(f"# HELP {prom} {family.description}")
            lines.append(f"# TYPE {prom} {family.type}")

        for sample in family.samples:
            label_parts = ",".join(f'{k}="{v}"' for k, v in sample.labels.items())
            label_str = f"{{{label_parts}}}" if label_parts else ""
            lines.append(f"{prom}{label_str} {sample.value}")

    return "\n".join(lines) + "\n"
