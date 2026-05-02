"""Training dataset generation and management."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_platform.models.mission import Mission
from spectra_platform.models.training import TrainingSample
from spectra_platform.models.user import User
from spectra_platform.models.user_preferences import UserPreferences

logger = logging.getLogger(__name__)

# Patterns to anonymize in training data
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")
_CREDENTIAL_PATTERN = re.compile(r"(password|passwd|pwd|secret|token|key|credential)\s*[:=]\s*\S+", re.IGNORECASE)
_PATH_PATTERN = re.compile(r"/(?:home|users|root)/\S+")


def anonymize_text(text: str) -> str:
    """Strip PII, IPs, credentials, and sensitive paths from text."""
    result = _IP_PATTERN.sub("<IP_ADDR>", text)
    result = _CREDENTIAL_PATTERN.sub(r"\1=<REDACTED>", result)
    result = _PATH_PATTERN.sub("<PATH>", result)
    return result


async def create_training_sample(
    session: AsyncSession,
    mission_id: str | None,
    user_id: str | None,
    sample_type: str,
    input_text: str,
    output_text: str,
    quality_score: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> TrainingSample:
    """Create an anonymized training sample from mission data."""
    sample = TrainingSample(
        mission_id=mission_id,
        user_id=user_id,
        sample_type=sample_type,
        input_text=anonymize_text(input_text),
        output_text=anonymize_text(output_text),
        quality_score=quality_score,
        metadata_=metadata,
        is_anonymized=True,
        is_approved=False,
    )
    session.add(sample)
    await session.flush()
    return sample


async def user_allows_training_data(session: AsyncSession, user_id: str) -> bool:
    """Return True only when account restrictions and training consent allow ingestion."""
    result = await session.execute(
        select(User.processing_restricted, UserPreferences.share_training_data)
        .join(UserPreferences, UserPreferences.user_id == User.id)
        .where(User.id == user_id)
    )
    row = result.one_or_none()
    if row is None:
        return False
    processing_restricted, share_training_data = row
    return bool(share_training_data) and not bool(processing_restricted)


async def create_mission_completion_sample(
    session: AsyncSession,
    mission: Mission,
    runtime_state: dict[str, Any],
) -> TrainingSample | None:
    """Capture one approved, consent-gated sample after successful mission completion."""
    if not mission.user_id or not await user_allows_training_data(session, str(mission.user_id)):
        return None

    existing = await session.execute(
        select(TrainingSample.id).where(
            and_(
                TrainingSample.mission_id == mission.id,
                TrainingSample.sample_type == "mission_completion",
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    findings = runtime_state.get("findings") or []
    input_payload = {
        "target": mission.target,
        "description": mission.description,
        "mission_type": mission.mission_type,
        "runtime_target": runtime_state.get("target"),
        "directive": runtime_state.get("directive"),
        "requirements": runtime_state.get("requirements", []),
    }
    output_payload = {
        "status": mission.status,
        "tools_run": runtime_state.get("tools_run", []),
        "findings": findings,
        "attack_surface": runtime_state.get("attack_surface", {}),
    }

    return await create_training_sample(
        session=session,
        mission_id=str(mission.id),
        user_id=str(mission.user_id),
        sample_type="mission_completion",
        input_text=json.dumps(input_payload, sort_keys=True),
        output_text=json.dumps(output_payload, sort_keys=True),
        quality_score=0.85 if findings else 0.65,
        metadata={
            "source": "mission_completion",
            "finding_count": len(findings),
            "tool_count": len(runtime_state.get("tools_run") or []),
        },
    )


async def get_dataset_stats(session: AsyncSession) -> dict[str, Any]:
    """Get dataset statistics by type."""
    result = await session.execute(
        select(
            TrainingSample.sample_type,
            func.count().label("count"),
            func.avg(TrainingSample.quality_score).label("avg_quality"),
        ).group_by(TrainingSample.sample_type)
    )
    rows = result.all()
    return {
        "types": {
            row.sample_type: {
                "count": row.count,
                "avg_quality": round(float(row.avg_quality or 0), 3),
            }
            for row in rows
        },
        "total": sum(row.count for row in rows),  # type: ignore[arg-type]
    }


async def export_dataset(
    session: AsyncSession,
    sample_types: list[str] | None = None,
    min_quality: float = 0.0,
    approved_only: bool = True,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Export training samples in JSONL-compatible format."""
    query = select(TrainingSample).where(TrainingSample.is_anonymized.is_(True))

    if approved_only:
        query = query.where(TrainingSample.is_approved.is_(True))
    if sample_types:
        query = query.where(TrainingSample.sample_type.in_(sample_types))
    if min_quality > 0:
        query = query.where(TrainingSample.quality_score >= min_quality)

    query = query.order_by(TrainingSample.created_at.desc()).limit(limit)
    result = await session.execute(query)
    samples = result.scalars().all()

    return [
        {
            "type": s.sample_type,
            "input": s.input_text,
            "output": s.output_text,
            "quality": s.quality_score,
            "metadata": s.metadata_,
        }
        for s in samples
    ]
