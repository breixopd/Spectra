"""Fine-tuning job execution handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.database import async_session_maker
from app.models.training import FineTuningJob
from app.services.training.backends import get_training_backend
from app.services.training.dataset import export_dataset


async def run_fine_tuning_job(job_id: str) -> dict[str, Any]:
    """Prepare an approved dataset and advance provider-specific fine-tuning state."""
    async with async_session_maker() as session:
        job = await session.get(FineTuningJob, job_id)
        if job is None:
            raise ValueError(f"Fine-tuning job not found: {job_id}")
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        job.status = "preparing"
        job.started_at = datetime.now(UTC)
        await session.commit()

        samples = await export_dataset(
            session,
            sample_types=job.sample_types,
            min_quality=float((job.config or {}).get("min_quality", 0.0)),
            approved_only=True,
        )
        backend = get_training_backend(job.provider)
        job.sample_count = len(samples)

        if not samples:
            job.status = "failed"
            job.metrics = {"error": "No approved training samples matched this job"}
            job.completed_at = datetime.now(UTC)
            await session.commit()
            return {"status": job.status, "job_id": job_id, "sample_count": 0}

        metrics = {
            "backend": backend.id,
            "backend_status": backend.status,
            "sample_count": len(samples),
            "base_model": job.base_model,
        }
        if backend.id == "local":
            job.status = "completed"
            job.output_model_path = f"training://local/{job.id}"
            metrics["mode"] = "dataset_prepared"
        else:
            job.status = "prepared"
            metrics["mode"] = "external_provider_ready"
            metrics["provider_config_fields"] = list(backend.config_fields)

        job.metrics = metrics
        job.completed_at = datetime.now(UTC)
        await session.commit()
        return {"status": job.status, "job_id": job_id, "sample_count": len(samples)}
