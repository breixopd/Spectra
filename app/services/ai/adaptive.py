"""Adaptive scanning strategy.

Learns from scan outcomes to optimize future scanning:
- Skip templates/tools that consistently find nothing for similar targets
- Prioritize tools that have been effective for similar service profiles
- Reduce scan time by eliminating low-yield techniques
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class ScanOutcome:
    """Record of a scan tool execution outcome."""
    tool_name: str
    target_type: str  # e.g., "web", "ssh", "mysql", "ftp"
    template_or_args: str  # e.g., nuclei template name or nmap script
    findings_count: int
    false_positive_count: int = 0
    scan_duration_seconds: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class AdaptiveScanner:
    """Learns from scan history to optimize future scanning strategies.

    Tracks which tools and templates are effective for which target types,
    and provides recommendations to skip low-yield scans.
    """

    def __init__(self, min_samples: int = 3, skip_threshold: float = 0.1):
        self._outcomes: list[ScanOutcome] = []
        self._min_samples = min_samples
        self._skip_threshold = skip_threshold  # Below this yield rate, skip

    def record_outcome(self, outcome: ScanOutcome):
        """Record the outcome of a scan."""
        self._outcomes.append(outcome)
        logger.debug("Recorded outcome: %s on %s -> %d findings",
                     outcome.tool_name, outcome.target_type, outcome.findings_count)

    def should_skip(self, tool_name: str, target_type: str,
                    template_or_args: str | None = None) -> tuple[bool, str]:
        """Determine if a scan should be skipped based on historical data.

        Returns (should_skip, reason).
        """
        matching = [o for o in self._outcomes
                    if o.tool_name == tool_name and o.target_type == target_type]

        if template_or_args:
            template_matching = [o for o in matching if o.template_or_args == template_or_args]
            if len(template_matching) >= self._min_samples:
                yield_rate = sum(1 for o in template_matching if o.findings_count > 0) / len(template_matching)
                if yield_rate < self._skip_threshold:
                    return True, f"Template '{template_or_args}' has {yield_rate:.0%} yield rate on {target_type} targets ({len(template_matching)} samples)"

        if len(matching) >= self._min_samples:
            yield_rate = sum(1 for o in matching if o.findings_count > 0) / len(matching)
            if yield_rate < self._skip_threshold:
                return True, f"{tool_name} has {yield_rate:.0%} yield rate on {target_type} targets ({len(matching)} samples)"

        return False, ""

    def get_recommended_tools(self, target_type: str, limit: int = 5) -> list[dict]:
        """Get recommended tools for a target type based on historical effectiveness."""
        tool_stats: dict[str, dict] = {}

        for o in self._outcomes:
            if o.target_type == target_type:
                if o.tool_name not in tool_stats:
                    tool_stats[o.tool_name] = {"total": 0, "hits": 0, "total_findings": 0, "avg_duration": 0}
                stats = tool_stats[o.tool_name]
                stats["total"] += 1
                if o.findings_count > 0:
                    stats["hits"] += 1
                stats["total_findings"] += o.findings_count
                stats["avg_duration"] = (stats["avg_duration"] * (stats["total"] - 1) + o.scan_duration_seconds) / stats["total"]

        recommendations = []
        for tool, stats in tool_stats.items():
            if stats["total"] >= self._min_samples:
                yield_rate = stats["hits"] / stats["total"]
                recommendations.append({
                    "tool": tool,
                    "yield_rate": round(yield_rate, 2),
                    "total_findings": stats["total_findings"],
                    "avg_duration": round(stats["avg_duration"], 1),
                    "samples": stats["total"],
                    "score": round(yield_rate * stats["total_findings"] / max(stats["avg_duration"], 1), 3),
                })

        recommendations.sort(key=lambda r: r["score"], reverse=True)
        return recommendations[:limit]

    async def persist(self):
        """Persist scan history to DB."""
        import json

        from sqlalchemy import text

        from app.core.database import async_session_maker

        data = [
            {
                "tool": o.tool_name, "target_type": o.target_type,
                "template": o.template_or_args, "findings": o.findings_count,
                "fp": o.false_positive_count, "duration": o.scan_duration_seconds,
                "ts": o.timestamp.isoformat(),
            }
            for o in self._outcomes[-500:]  # Keep last 500
        ]
        try:
            async with async_session_maker() as session:
                await session.execute(
                    text("""
                        INSERT INTO system_cache (key, value, expires_at)
                        VALUES ('adaptive_scan_data', :value, now() + interval '180 days')
                        ON CONFLICT (key) DO UPDATE SET value = :value
                    """),
                    {"value": json.dumps(data)}
                )
                await session.commit()
        except Exception:
            pass

    async def restore(self):
        """Restore scan history from DB."""
        import json

        from sqlalchemy import text

        from app.core.database import async_session_maker

        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    text("SELECT value FROM system_cache WHERE key = 'adaptive_scan_data'")
                )
                row = result.fetchone()
                if row:
                    data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    for d in data:
                        self._outcomes.append(ScanOutcome(
                            tool_name=d["tool"], target_type=d["target_type"],
                            template_or_args=d["template"], findings_count=d["findings"],
                            false_positive_count=d.get("fp", 0),
                            scan_duration_seconds=d.get("duration", 0),
                            timestamp=datetime.fromisoformat(d["ts"]),
                        ))
        except Exception:
            pass


# Singleton
_adaptive: AdaptiveScanner | None = None

def get_adaptive_scanner() -> AdaptiveScanner:
    global _adaptive
    if _adaptive is None:
        _adaptive = AdaptiveScanner()
    return _adaptive
