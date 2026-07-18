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

import asyncio
import inspect
import json as _json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
_MISSING = object()


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

    def __init__(self, mission_manager=None, *, poll_interval_seconds: float = 1.0):
        self.mission_manager = mission_manager
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))

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
            if not self.mission_manager:
                run.errors.append("Mission manager is not configured")
                return run

            mission_ref = self.mission_manager.start_mission(
                target=target.target,
                directive=f"Security assessment of {target.name}",
                scan_mode="autonomous",
                pentest_framework="ptes",
            )
            if inspect.isawaitable(mission_ref):
                mission_ref = await mission_ref
            run.mission_id = self._mission_id(mission_ref)
            if not run.mission_id:
                raise ValueError("Mission manager returned no mission ID")

            mission_state = await self._wait_for_terminal_state(run.mission_id, timeout)
            self._populate_metrics(run, mission_state)

            status = self._status(mission_state)
            valid, postcondition_errors = self._validate_postconditions(target, status, run)
            run.success = valid
            run.errors.extend(postcondition_errors)

        except TimeoutError:
            run.errors.append(f"Mission did not reach a terminal state within {timeout:.1f}s")

        except Exception as exc:
            run.errors.append(str(exc))
        finally:
            run.end_time = time.time()

        return run

    async def _wait_for_terminal_state(self, mission_id: str, timeout: float) -> Any:
        """Poll mission state until completion, failure, or cancellation."""

        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            state = await self._get_mission_state(mission_id)
            if state is not None and self._status(state) in {
                "completed",
                "complete",
                "success",
                "succeeded",
                "failed",
                "cancelled",
                "stopped",
                "timed_out",
                "timeout",
                "error",
            }:
                return state

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Mission {mission_id} did not reach a terminal state")
            await asyncio.sleep(min(self.poll_interval_seconds, remaining))

    async def _get_mission_state(self, mission_id: str) -> Any:
        """Read state from common manager/lifecycle interfaces.

        The public manager returns an in-memory Mission object, while adapters
        and test harnesses often expose a mapping or a dedicated state getter.
        Supporting both keeps benchmark evaluation independent of deployment
        topology.
        """

        owners = [self.mission_manager]
        lifecycle = getattr(self.mission_manager, "lifecycle", None)
        if lifecycle is not None:
            owners.append(lifecycle)

        for owner in owners:
            if owner is None:
                continue
            for getter_name in ("get_mission", "get_mission_state", "get_status"):
                getter = getattr(owner, getter_name, None)
                if getter is None:
                    continue
                try:
                    state = getter(mission_id)
                    if inspect.isawaitable(state):
                        state = await state
                except (OSError, RuntimeError, KeyError, TypeError, AttributeError) as exc:
                    logger.debug("Mission state poll failed via %s: %s", getter_name, exc)
                    continue
                if state is not None:
                    if getter_name == "get_status" and isinstance(state, str):
                        return {"status": state}
                    return state
        return None

    @staticmethod
    def _mission_id(mission_ref: Any) -> str:
        """Normalize a manager's string, UUID, or Mission return value."""

        if isinstance(mission_ref, str):
            return mission_ref
        if isinstance(mission_ref, Mapping):
            value = mission_ref.get("id") or mission_ref.get("mission_id")
            return str(value) if value else ""
        value = getattr(mission_ref, "id", mission_ref)
        return str(value) if value else ""

    @staticmethod
    def _state_value(state: Any, key: str, default: Any = None) -> Any:
        if isinstance(state, Mapping):
            value = state.get(key, _MISSING)
            if value is not _MISSING:
                return value
            summary = state.get("summary")
            if isinstance(summary, Mapping):
                return summary.get(key, default)
            return default
        value = getattr(state, key, _MISSING)
        if value is not _MISSING:
            return value
        summary = getattr(state, "summary", None)
        if isinstance(summary, Mapping):
            return summary.get(key, default)
        return default

    @classmethod
    def _status(cls, state: Any) -> str:
        raw = state if isinstance(state, str) else cls._state_value(state, "status", "unknown")
        return str(getattr(raw, "value", raw)).strip().lower()

    @classmethod
    def _milestone_ids(cls, state: Any) -> list[str]:
        raw = cls._state_value(state, "milestones", []) or cls._state_value(state, "completed_milestones", [])
        if isinstance(raw, Mapping):
            raw = [raw]
        completed: list[str] = []
        for entry in raw if isinstance(raw, list) else []:
            if isinstance(entry, str):
                completed.append(entry)
                continue
            if not isinstance(entry, Mapping):
                continue
            milestone_id = entry.get("milestone") or entry.get("id") or entry.get("name")
            status = str(entry.get("status", "completed")).lower()
            if milestone_id and status in {"completed", "complete", "done", "success", "succeeded"}:
                completed.append(str(milestone_id))
        return list(dict.fromkeys(completed))

    @classmethod
    def _finding_labels(cls, state: Any) -> list[str]:
        raw = cls._state_value(state, "findings", []) or cls._state_value(state, "findings_found", [])
        labels: list[str] = []
        for entry in raw if isinstance(raw, list) else []:
            if isinstance(entry, str):
                labels.append(entry)
            elif isinstance(entry, Mapping):
                value = entry.get("title") or entry.get("name") or entry.get("id")
                if value:
                    labels.append(str(value))
            else:
                value = getattr(entry, "title", None) or getattr(entry, "name", None)
                if value:
                    labels.append(str(value))
        return labels

    @classmethod
    def _populate_metrics(cls, run: BenchmarkRun, state: Any) -> None:
        run.milestones_completed = cls._milestone_ids(state)
        run.findings_found = cls._finding_labels(state)
        tool_executions = cls._state_value(state, "tool_executions", []) or []
        tools_run = cls._state_value(state, "tools_run", []) or []
        run.tool_calls = int(cls._state_value(state, "tool_calls", len(tool_executions) or len(tools_run)) or 0)
        run.llm_calls = int(cls._state_value(state, "llm_calls", 0) or 0)
        run.estimated_cost = float(
            cls._state_value(state, "estimated_cost", cls._state_value(state, "estimated_cost_usd", 0.0)) or 0.0
        )

    @staticmethod
    def _validate_postconditions(
        target: BenchmarkTarget,
        status: str,
        run: BenchmarkRun,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        successful_status = status in {"completed", "complete", "success", "succeeded"}
        if not successful_status:
            errors.append(f"Mission ended with non-success status: {status}")

        completed = set(run.milestones_completed)
        missing_milestones = [item for item in target.expected_milestones if item not in completed]
        if missing_milestones:
            errors.append(f"Missing expected milestones: {', '.join(missing_milestones)}")

        findings = [finding.lower() for finding in run.findings_found]
        missing_vulns = [
            expected
            for expected in target.expected_vulns
            if not any(expected.lower() in finding for finding in findings)
        ]
        if missing_vulns:
            errors.append(f"Missing expected findings: {', '.join(missing_vulns)}")

        return successful_status and not missing_milestones and not missing_vulns, errors


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
