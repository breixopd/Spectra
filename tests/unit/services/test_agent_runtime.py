"""Regression tests for the agent task runtime and benchmark harness."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from spectra_billing.training.benchmark import BenchmarkRunner, BenchmarkTarget
from spectra_mission.coordination.orchestrator import (
    Orchestrator,
    TaskExecStatus,
)
from spectra_mission.coordination.task_decomposer import MicroTask, _stable_task_digest


class _AllowAllScope:
    """Small scope double that keeps orchestration tests focused on execution."""

    def validate(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, blocked_by="")


def _task(task_id: str, *, depends_on: list[str] | None = None, retries: int = 0, **kwargs: Any) -> MicroTask:
    return MicroTask(
        id=task_id,
        tool_name=task_id,
        tool_args={},
        technique_category="port_scanning",
        phase="discovery",
        depends_on=depends_on or [],
        max_retries=retries,
        **kwargs,
    )


def test_decomposed_ids_are_stable_across_python_hash_seeds() -> None:
    """Task IDs must be safe to persist and resume across worker processes."""

    source = """
import json
from spectra_mission.coordination.task_decomposer import TaskDecomposer

task = {"agent_type": "scan", "args": {"target": "example.test", "ports": [443, 80]}}
print(json.dumps([item.id for item in TaskDecomposer().decompose(task, "discovery")]))
"""
    repo_root = Path(__file__).parents[3]
    source_paths = [str(path) for path in sorted(repo_root.glob("packages/*/src"))]
    source_paths.extend(str(path) for path in sorted(repo_root.glob("services/*/src")))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(source_paths)}

    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", source],
            cwd=repo_root,
            env={**env, "PYTHONHASHSEED": seed},
            text=True,
        ).strip()
        for seed in ("1", "987654")
    ]

    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])


def test_benchmark_mission_id_accepts_mapping_adapters() -> None:
    assert BenchmarkRunner._mission_id({"mission_id": "m-42"}) == "m-42"
    assert BenchmarkRunner._mission_id({"id": 42}) == "42"


@given(st.dictionaries(st.text(min_size=1, max_size=12), st.integers(), max_size=5))
def test_task_digest_is_canonical_for_equivalent_json_objects(task: dict[str, int]) -> None:
    reversed_task = dict(reversed(list(task.items())))
    assert _stable_task_digest(task, "discovery") == _stable_task_digest(reversed_task, "discovery")


def test_orchestrator_scope_checks_use_each_task_phase() -> None:
    phases: list[str] = []

    class PhaseAwareScope:
        def validate(self, _action: str, _technique: str, phase: str) -> SimpleNamespace:
            phases.append(phase)
            return SimpleNamespace(allowed=True, blocked_by="")

    orchestrator = Orchestrator(PhaseAwareScope())
    orchestrator._scope_check_all([_task("discovery-task"), _task("report-task")], "discovery")
    orchestrator._scope_check_all(
        [
            _task("discovery-task"),
            MicroTask(
                id="report-task",
                tool_name="report",
                tool_args={},
                technique_category="port_scanning",
                phase="reporting",
            ),
        ],
        "discovery",
    )

    assert phases[-2:] == ["discovery", "reporting"]


@pytest.mark.asyncio
async def test_orchestrator_supports_sync_executor_and_async_progress_callback() -> None:
    events: list[TaskExecStatus] = []

    def sync_executor(tool_name: str, _tool_args: dict[str, Any]) -> dict[str, str]:
        return {"tool": tool_name}

    async def progress(record: Any) -> None:
        events.append(record.status)

    result = await Orchestrator(_AllowAllScope(), sync_executor, retry_base_delay=0).execute(
        [_task("sync-tool")], progress_callback=progress
    )

    assert result.all_successful
    assert result.completed == 1
    assert result.records[0].result == {"tool": "sync-tool"}
    assert events == [TaskExecStatus.COMPLETED]


@pytest.mark.asyncio
async def test_orchestrator_retries_timeout_without_retrying_cancellation() -> None:
    attempts = 0

    async def slow_executor(_tool_name: str, _tool_args: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(1)

    timeout_result = await Orchestrator(_AllowAllScope(), slow_executor, retry_base_delay=0).execute(
        [_task("timeout", retries=1, timeout_seconds=0.01)]
    )

    assert timeout_result.failed == 1
    assert timeout_result.records[0].retries == 2
    assert "timed out" in timeout_result.records[0].error.lower()
    assert attempts == 2

    cancellation_attempts = 0

    async def cancelled_executor(_tool_name: str, _tool_args: dict[str, Any]) -> None:
        nonlocal cancellation_attempts
        cancellation_attempts += 1
        raise asyncio.CancelledError

    cancelled_result = await Orchestrator(_AllowAllScope(), cancelled_executor, retry_base_delay=0).execute(
        [_task("cancelled", retries=5)]
    )

    assert cancelled_result.cancelled == 1
    assert cancelled_result.records[0].status == TaskExecStatus.CANCELLED
    assert cancelled_result.records[0].retries == 0
    assert cancellation_attempts == 1
    assert not cancelled_result.all_successful


@pytest.mark.asyncio
async def test_orchestrator_marks_dependency_deadlocks_and_failed_dependencies_skipped() -> None:
    async def failing_executor(_tool_name: str, _tool_args: dict[str, Any]) -> None:
        raise RuntimeError("tool failed")

    tasks = [
        _task("failed", retries=0),
        _task("dependent", depends_on=["failed"]),
        _task("cycle-a", depends_on=["cycle-b"]),
        _task("cycle-b", depends_on=["cycle-a"]),
    ]
    result = await Orchestrator(_AllowAllScope(), failing_executor, retry_base_delay=0).execute(tasks)
    records = {record.task.id: record for record in result.records}

    assert result.failed == 1
    assert result.skipped == 3
    assert records["dependent"].status == TaskExecStatus.SKIPPED
    assert "dependency" in records["dependent"].blocked_reason
    assert records["cycle-a"].status == TaskExecStatus.SKIPPED
    assert "deadlock" in records["cycle-a"].blocked_reason
    assert not result.all_successful


@pytest.mark.asyncio
async def test_benchmark_waits_for_terminal_state_and_validates_postconditions() -> None:
    class FakeMissionManager:
        def __init__(self) -> None:
            self.polls = 0

        async def start_mission(self, **_kwargs: Any) -> str:
            return "mission-123"

        async def get_mission(self, _mission_id: str) -> dict[str, Any]:
            self.polls += 1
            if self.polls == 1:
                return {"status": "running", "milestones": []}
            return {
                "status": "completed",
                "milestones": [{"milestone": "m1_target_enumeration", "status": "completed"}],
                "findings": [{"title": "SQL Injection"}],
                "tools_run": ["nmap", "sqlmap"],
                "tool_calls": 3,
                "llm_calls": 2,
                "estimated_cost": 0.12,
            }

    manager = FakeMissionManager()
    runner = BenchmarkRunner(manager, poll_interval_seconds=0)
    run = await runner._run_single(
        BenchmarkTarget(
            name="fixture",
            target="fixture",
            expected_vulns=["SQL Injection"],
            expected_milestones=["m1_target_enumeration"],
        ),
        timeout=1,
    )

    assert run.success
    assert run.mission_id == "mission-123"
    assert run.milestones_completed == ["m1_target_enumeration"]
    assert run.findings_found == ["SQL Injection"]
    assert run.tool_calls == 3
    assert run.llm_calls == 2
    assert run.estimated_cost == pytest.approx(0.12)
    assert manager.polls == 2


@pytest.mark.asyncio
async def test_benchmark_rejects_terminal_mission_with_missing_postconditions() -> None:
    class IncompleteMissionManager:
        async def start_mission(self, **_kwargs: Any) -> str:
            return "mission-incomplete"

        async def get_mission(self, _mission_id: str) -> dict[str, Any]:
            return {"status": "completed", "milestones": [], "findings": []}

    run = await BenchmarkRunner(IncompleteMissionManager(), poll_interval_seconds=0)._run_single(
        BenchmarkTarget(
            name="incomplete",
            target="fixture",
            expected_vulns=["SQL Injection"],
            expected_milestones=["m1_target_enumeration"],
        ),
        timeout=1,
    )

    assert not run.success
    assert any("Missing expected milestones" in error for error in run.errors)
    assert any("Missing expected findings" in error for error in run.errors)
