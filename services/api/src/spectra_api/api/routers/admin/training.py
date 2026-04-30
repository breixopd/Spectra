"""Admin training dataset and fine-tuning management endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_session
from app.infrastructure.queue import PostgresJobQueue
from app.models.training import FineTuningJob, TrainingSample
from app.models.user import User
from app.services.training.backends import get_training_backend, list_training_backends
from app.services.training.dataset import export_dataset, get_dataset_stats
from spectra_api.authz import Permission, require_permission
from spectra_domain.jobs import WorkerJobName

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/admin/training/stats")
async def dataset_stats(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Get training dataset statistics."""
    return await get_dataset_stats(session)


@router.get("/api/v1/admin/training/samples")
async def list_samples(
    sample_type: str | None = Query(None),
    approved: bool | None = Query(None),
    min_quality: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """List training samples with filtering."""
    query = select(TrainingSample)
    count_query = select(func.count()).select_from(TrainingSample)

    if sample_type:
        query = query.where(TrainingSample.sample_type == sample_type)
        count_query = count_query.where(TrainingSample.sample_type == sample_type)
    if approved is not None:
        query = query.where(TrainingSample.is_approved == approved)
        count_query = count_query.where(TrainingSample.is_approved == approved)
    if min_quality > 0:
        query = query.where(TrainingSample.quality_score >= min_quality)
        count_query = count_query.where(TrainingSample.quality_score >= min_quality)

    total = (await session.execute(count_query)).scalar() or 0
    offset = (page - 1) * per_page
    query = query.order_by(TrainingSample.created_at.desc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    samples = result.scalars().all()

    return {
        "items": [
            {
                "id": s.id,
                "sample_type": s.sample_type,
                "input_preview": s.input_text[:200],
                "output_preview": s.output_text[:200],
                "quality_score": s.quality_score,
                "is_approved": s.is_approved,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in samples
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/api/v1/admin/training/samples/{sample_id}/approve")
async def approve_sample(
    sample_id: str,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Approve a training sample for inclusion in datasets."""
    result = await session.execute(
        update(TrainingSample).where(TrainingSample.id == sample_id).values(is_approved=True)
    )
    if cast(CursorResult, result).rowcount == 0:
        raise HTTPException(status_code=404, detail="Sample not found")
    await session.commit()
    return {"status": "approved"}


@router.post("/api/v1/admin/training/samples/bulk-approve")
async def bulk_approve_samples(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Bulk approve samples by type and quality threshold."""
    body = await request.json()
    sample_type = body.get("sample_type")
    min_quality = body.get("min_quality", 0.7)

    query = update(TrainingSample).where(
        TrainingSample.is_approved.is_(False),
        TrainingSample.quality_score >= min_quality,
    )
    if sample_type:
        query = query.where(TrainingSample.sample_type == sample_type)

    query = query.values(is_approved=True)
    result = await session.execute(query)
    await session.commit()
    return {"approved_count": cast(CursorResult, result).rowcount}


@router.get("/api/v1/admin/training/export")
async def export_training_data(
    format: str = Query("jsonl", pattern="^(jsonl|json)$"),
    sample_type: str | None = Query(None),
    min_quality: float = Query(0.0, ge=0.0, le=1.0),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Export approved-only training data for fine-tuning (unapproved rows are never exported)."""
    types = [sample_type] if sample_type else None
    samples = await export_dataset(session, sample_types=types, min_quality=min_quality, approved_only=True)

    if format == "jsonl":
        lines = [json.dumps(s, default=str) + "\n" for s in samples]
        content = "".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=spectra_training_data.jsonl"},
        )

    content = json.dumps(samples, default=str, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=spectra_training_data.json"},
    )


# --- Fine-tuning Job Management ---


@router.get("/api/v1/admin/training/jobs")
async def list_jobs(
    status: str | None = Query(None),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """List fine-tuning jobs."""
    query = select(FineTuningJob)
    if status:
        query = query.where(FineTuningJob.status == status)
    query = query.order_by(FineTuningJob.created_at.desc())

    result = await session.execute(query)
    jobs = result.scalars().all()

    return {
        "jobs": [
            {
                "id": j.id,
                "name": j.name,
                "status": j.status,
                "base_model": j.base_model,
                "sample_count": j.sample_count,
                "provider": j.provider,
                "provider_job_id": j.provider_job_id,
                "output_model_path": j.output_model_path,
                "error_message": j.error_message,
                "metrics": j.metrics,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    }


@router.post("/api/v1/admin/training/jobs")
async def create_job(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new fine-tuning job."""
    body = await request.json()

    # Count available samples
    sample_types = body.get("sample_types", [])
    min_quality = body.get("min_quality", 0.5)

    count_query = (
        select(func.count())
        .select_from(TrainingSample)
        .where(
            TrainingSample.is_approved.is_(True),
            TrainingSample.quality_score >= min_quality,
        )
    )
    if sample_types:
        count_query = count_query.where(TrainingSample.sample_type.in_(sample_types))

    sample_count = (await session.execute(count_query)).scalar() or 0
    provider = body.get("provider", "local")
    try:
        get_training_backend(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown training provider")
    config = dict(body.get("config") or {})
    config["min_quality"] = min_quality

    job = FineTuningJob(
        name=body.get("name", f"fine-tune-{sample_count}-samples"),
        status="pending",
        base_model=body.get("base_model", ""),
        sample_count=sample_count,
        sample_types=sample_types or None,
        config=config,
        provider=provider,
        created_by=_user.id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    try:
        queue = PostgresJobQueue(settings.TOOL_QUEUE_NAME)
        queue_job_id = await queue.enqueue_job(WorkerJobName.RUN_FINE_TUNING, job_id=job.id, _timeout=3600)
    except (OSError, RuntimeError, ConnectionError) as exc:
        logger.error("Failed to enqueue fine-tuning job %s: %s", job.id, exc)
        job.status = "queue_failed"
        job.metrics = {"error": str(exc)}
        await session.commit()
        raise HTTPException(status_code=503, detail="Fine-tuning job could not be enqueued") from exc

    return {
        "id": job.id,
        "name": job.name,
        "status": job.status,
        "sample_count": sample_count,
        "queue_job_id": queue_job_id,
    }


@router.delete("/api/v1/admin/training/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Cancel a pending/running fine-tuning job."""
    result = await session.execute(
        update(FineTuningJob)
        .where(FineTuningJob.id == job_id, FineTuningJob.status.in_(["pending", "preparing", "training"]))
        .values(status="cancelled")
    )
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="Job not found or already completed")
    await session.commit()
    return {"status": "cancelled"}


# --- GPU Provider Configuration ---


@router.get("/api/v1/admin/training/providers")
async def list_providers(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """List available fine-tuning compute providers."""
    return {"providers": list_training_backends()}
