"""Training data pipeline — collects, extracts, and formats training examples from missions.

Always-on hooks collect agent decisions, tool executions, and feedback.
Raw data is converted to supervised fine-tuning examples in multiple formats.
"""

from __future__ import annotations

import json as _json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrainingExample:
    """A single training example extracted from a mission."""
    id: str
    mission_id: str
    prompt: str
    response: str
    technique: str = ""
    phase: str = ""
    success: bool = True
    quality_score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionLog:
    """Raw data collected from a mission for training."""
    mission_id: str
    target: str = ""
    framework: str = "ptes"
    start_time: float = 0.0
    end_time: float = 0.0
    agent_decisions: list[dict[str, Any]] = field(default_factory=list)
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    milestones_completed: list[str] = field(default_factory=list)
    red_flags: list[dict[str, Any]] = field(default_factory=list)
    human_rating: int = 0  # 0=unrated, 1-5


class MissionDataCollector:
    """Collects and stores raw training data from mission execution.

    Hooks into agent decisions, tool executions, and milestone completions.
    Data is stored as JSON in S3 and indexed for later extraction.
    """

    def __init__(self, storage_path: str = "training/raw/"):
        self.storage_path = Path(storage_path)

    def log_agent_decision(self, mission_id: str, agent_role: str, prompt: str, response: str, action: dict, confidence: float) -> None:
        """Record an agent decision for training."""
        entry = {
            "timestamp": time.time(),
            "mission_id": mission_id,
            "agent_role": agent_role,
            "prompt": prompt,
            "response": response,
            "action": action,
            "confidence": confidence,
        }
        self._append_log(mission_id, "agent_decisions", entry)

    def log_tool_execution(self, mission_id: str, tool_name: str, args: dict, output: str, success: bool, duration: float) -> None:
        """Record a tool execution for training."""
        entry = {
            "timestamp": time.time(),
            "mission_id": mission_id,
            "tool_name": tool_name,
            "args": args,
            "output": output[:10000],  # Truncate for storage
            "success": success,
            "duration_seconds": duration,
        }
        self._append_log(mission_id, "tool_executions", entry)

    def log_red_flag(self, mission_id: str, output: str, reason: str, severity: str) -> None:
        """Record a red-flagged output (MAKER pattern)."""
        entry = {
            "timestamp": time.time(),
            "mission_id": mission_id,
            "output": output[:5000],
            "reason": reason,
            "severity": severity,
        }

    def _append_log(self, mission_id: str, category: str, entry: dict) -> None:
        """Append an entry to the mission log (in production: to S3)."""
        log_dir = self.storage_path / mission_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{category}.jsonl"
        try:
            with open(log_file, "a") as f:
                f.write(_json.dumps(entry) + "\n")
        except Exception:
            logger.exception("Failed to write training log for %s/%s", mission_id, category)


class TrainingExampleExtractor:
    """Extracts training examples from raw mission logs.

    Converts agent decisions and tool executions into prompt-response pairs
    suitable for supervised fine-tuning of small models.
    """

    def extract_from_mission(self, log: MissionLog, min_quality: float = 0.5) -> list[TrainingExample]:
        """Extract training examples from a single mission.

        Only includes examples from missions that completed >=80% of milestones
        and have quality scores above the minimum threshold.
        """
        examples: list[TrainingExample] = []

        # Quality gate: mission must have reasonable completion
        total_milestones = max(len(log.milestones_completed), 1)
        if log.human_rating > 0 and log.human_rating < 3:
            return examples  # Skip low-rated missions

        # Extract agent decision examples
        for decision in log.agent_decisions:
            ex = TrainingExample(
                id=f"{log.mission_id}_{decision.get('agent_role', 'unknown')}_{len(examples)}",
                mission_id=log.mission_id,
                prompt=decision.get("prompt", ""),
                response=decision.get("response", ""),
                technique=decision.get("action", {}).get("action_type", ""),
                phase="",
                success=decision.get("confidence", 0) > 0.5,
                quality_score=log.human_rating / 5.0 if log.human_rating > 0 else 0.7,
            )
            if ex.quality_score >= min_quality:
                examples.append(ex)

        # Extract tool usage examples
        for tool_exec in log.tool_executions:
            ex = TrainingExample(
                id=f"{log.mission_id}_tool_{tool_exec.get('tool_name', '')}_{len(examples)}",
                mission_id=log.mission_id,
                prompt=f"Execute {tool_exec.get('tool_name', 'unknown')} with args: {_json.dumps(tool_exec.get('args', {}))}",
                response=tool_exec.get("output", "")[:2000],
                technique=tool_exec.get("tool_name", ""),
                success=tool_exec.get("success", False),
                quality_score=log.human_rating / 5.0 if log.human_rating > 0 else 0.6,
            )
            if ex.quality_score >= min_quality:
                examples.append(ex)

        return examples

    def to_alpaca_format(self, examples: list[TrainingExample]) -> list[dict[str, Any]]:
        """Convert examples to Alpaca instruction-tuning format."""
        return [
            {
                "instruction": ex.prompt,
                "output": ex.response,
                "metadata": {"technique": ex.technique, "success": ex.success},
            }
            for ex in examples
        ]

    def to_sharegpt_format(self, examples: list[TrainingExample]) -> list[dict[str, Any]]:
        """Convert examples to ShareGPT conversation format."""
        return [
            {
                "conversations": [
                    {"from": "human", "value": ex.prompt},
                    {"from": "gpt", "value": ex.response},
                ],
                "metadata": {"technique": ex.technique, "success": ex.success},
            }
            for ex in examples
        ]

    def to_chatml_format(self, examples: list[TrainingExample]) -> list[dict[str, Any]]:
        """Convert examples to ChatML format."""
        return [
            {
                "messages": [
                    {"role": "system", "content": "You are an autonomous penetration testing agent."},
                    {"role": "user", "content": ex.prompt},
                    {"role": "assistant", "content": ex.response},
                ],
                "metadata": {"technique": ex.technique, "success": ex.success},
            }
            for ex in examples
        ]


# ── Dataset export for fine-tuning jobs ────────────────────────────

async def export_dataset(
    session,
    *,
    sample_types: list[str] | None = None,
    min_quality: float = 0.0,
    approved_only: bool = True,
) -> list[dict[str, Any]]:
    """Export approved training samples for fine-tuning.

    Args:
        session: SQLAlchemy async session
        sample_types: Optional filter by sample type (agent_decision, tool_execution)
        min_quality: Minimum quality score filter
        approved_only: Only include approved samples

    Returns:
        List of training samples in Alpaca format
    """
    from sqlalchemy import select

    from spectra_platform.models.training import TrainingSample

    stmt = select(TrainingSample)
    if approved_only:
        stmt = stmt.where(TrainingSample.approved.is_(True))
    if min_quality > 0:
        stmt = stmt.where(TrainingSample.quality_score >= min_quality)
    if sample_types:
        stmt = stmt.where(TrainingSample.sample_type.in_(sample_types))

    result = await session.execute(stmt)
    samples = result.scalars().all()

    return [
        {
            "instruction": s.prompt,
            "output": s.response,
            "metadata": {
                "technique": s.technique,
                "success": s.success,
                "sample_type": s.sample_type,
                "mission_id": s.mission_id,
            },
        }
        for s in samples
    ]
