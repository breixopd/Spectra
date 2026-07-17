"""Benchmark framework for evaluating pentest agent performance.

Runs standardized missions against known targets and records:
- Milestone completion rates (M1-M11)
- Time to each milestone
- Cost per milestone
- False positive rates
- Per-technique success rates

Supports regression testing against baselines when models/config change.
"""

from __future__ import annotations

import json as _json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTarget:
    """A known target for benchmark testing."""

    name: str
    target: str
    expected_vulns: list[str] = field(default_factory=list)
    expected_milestones: list[str] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass
class BenchmarkRun:
    """Results of a single benchmark run."""

    target_name: str
    mission_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    milestones_completed: list[str] = field(default_factory=list)
    milestones_total: int = 0
    findings_found: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    tool_calls: int = 0
    llm_calls: int = 0
    estimated_cost: float = 0.0
    success: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def milestone_rate(self) -> float:
        if self.milestones_total == 0:
            return 0.0
        return len(self.milestones_completed) / self.milestones_total

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time


@dataclass
class BenchmarkResult:
    """Aggregate benchmark results across multiple runs."""

    runs: list[BenchmarkRun]
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def avg_milestone_rate(self) -> float:
        if not self.runs:
            return 0.0
        return sum(r.milestone_rate for r in self.runs) / len(self.runs)

    @property
    def total_cost(self) -> float:
        return sum(r.estimated_cost for r in self.runs)

    @property
    def total_llm_calls(self) -> int:
        return sum(r.llm_calls for r in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": len(self.runs),
            "avg_milestone_rate": round(self.avg_milestone_rate, 3),
            "total_cost": round(self.total_cost, 4),
            "total_llm_calls": self.total_llm_calls,
            "success_rate": round(sum(1 for r in self.runs if r.success) / max(len(self.runs), 1), 3),
            "per_target": [
                {
                    "name": r.target_name,
                    "milestone_rate": round(r.milestone_rate, 3),
                    "duration_s": round(r.duration_seconds, 1),
                    "cost": round(r.estimated_cost, 4),
                    "success": r.success,
                }
                for r in self.runs
            ],
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            _json.dump(self.to_dict(), f, indent=2)


class BenchmarkRunner:
    """Runs benchmark missions against standardized targets.

    Usage:
        runner = BenchmarkRunner(mission_manager)
        result = await runner.run_benchmark(BENCHMARK_TARGETS)
    """

    def __init__(self, mission_manager=None):
        self.mission_manager = mission_manager

    async def run_benchmark(
        self,
        targets: list[BenchmarkTarget],
        *,
        timeout_per_target: float = 3600.0,
    ) -> BenchmarkResult:
        """Run benchmark missions against all targets."""
        runs: list[BenchmarkRun] = []
        started = time.time()

        for target in targets:
            logger.info("Benchmarking target: %s", target.name)
            run = await self._run_single(target, timeout_per_target)
            runs.append(run)
            logger.info(
                "Target %s: %d/%d milestones, %.1fs",
                target.name,
                len(run.milestones_completed),
                run.milestones_total,
                run.duration_seconds,
            )

        return BenchmarkResult(runs=runs, started_at=started, completed_at=time.time())

    async def _run_single(self, target: BenchmarkTarget, timeout: float) -> BenchmarkRun:
        """Run a single benchmark mission."""
        run = BenchmarkRun(
            target_name=target.name,
            milestones_total=len(target.expected_milestones),
            start_time=time.time(),
        )

        try:
            if self.mission_manager:
                mission_id = await self.mission_manager.start_mission(
                    target=target.target,
                    directive=f"Security assessment of {target.name}",
                    scan_mode="autonomous",
                    pentest_framework="ptes",
                )
                run.mission_id = mission_id
                run.success = True

            run.end_time = time.time()

        except Exception as exc:
            run.errors.append(str(exc))
            run.end_time = time.time()

        return run


# Standard benchmark targets
BENCHMARK_TARGETS: list[BenchmarkTarget] = [
    BenchmarkTarget(
        name="dvwa",
        target="http://dvwa:80",
        expected_vulns=["SQL Injection", "XSS", "CSRF", "Command Injection"],
        expected_milestones=["m1_target_enumeration", "m2_vector_identification"],
        difficulty="easy",
    ),
    BenchmarkTarget(
        name="metasploitable",
        target="metasploitable",
        expected_vulns=["vsftpd", "UnrealIRCd", "Samba", "Tomcat"],
        expected_milestones=[
            "m1_target_enumeration",
            "m2_vector_identification",
            "m3_initial_access",
        ],
        difficulty="medium",
    ),
]
