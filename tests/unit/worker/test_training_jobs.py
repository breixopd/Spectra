from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from spectra_domain.jobs import WorkerJobName
from spectra_platform.models.training import FineTuningJob
from spectra_worker import _WORKER_FUNCTIONS
from spectra_worker.training_jobs import run_fine_tuning_job


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _job(provider: str = "local", config: dict | None = None) -> FineTuningJob:
    job = FineTuningJob(
        id="job-1",
        name="demo",
        status="pending",
        base_model="base",
        sample_count=0,
        sample_types=["mission_completion"],
        config=config or {"min_quality": 0.7},
        provider=provider,
        created_by="u1",
    )
    return job


def test_training_job_name_is_registered_with_worker():
    worker_names = {fn.__name__ for fn in _WORKER_FUNCTIONS}

    assert run_fine_tuning_job.__name__ == WorkerJobName.RUN_FINE_TUNING
    assert run_fine_tuning_job.__name__ in worker_names


def test_worker_job_name_enum_covers_all_registered_functions() -> None:
    worker_names = {fn.__name__ for fn in _WORKER_FUNCTIONS}
    enum_values = {member.value for member in WorkerJobName}
    assert worker_names == enum_values


@pytest.mark.asyncio
async def test_run_fine_tuning_job_completes_local_dataset_preparation():
    job = _job()
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with (
        patch("spectra_worker.training_jobs.async_session_maker", return_value=_SessionContext(session)),
        patch(
            "spectra_worker.training_jobs.export_dataset",
            new=AsyncMock(return_value=[{"input": "i", "output": "o"}]),
        ) as export_dataset,
    ):
        result = await run_fine_tuning_job("job-1")

    assert result == {"status": "completed", "job_id": "job-1", "sample_count": 1}
    assert job.status == "completed"
    assert job.output_model_path == "training://local/job-1"
    assert job.metrics["mode"] == "dataset_prepared"
    export_dataset.assert_awaited_once_with(
        session,
        sample_types=["mission_completion"],
        min_quality=0.7,
        approved_only=True,
    )


@pytest.mark.asyncio
async def test_run_fine_tuning_job_fails_without_matching_samples():
    job = _job()
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with (
        patch("spectra_worker.training_jobs.async_session_maker", return_value=_SessionContext(session)),
        patch("spectra_worker.training_jobs.export_dataset", new=AsyncMock(return_value=[])),
    ):
        result = await run_fine_tuning_job("job-1")

    assert result == {"status": "failed", "job_id": "job-1", "sample_count": 0}
    assert job.status == "failed"
    assert job.error_message == "No approved training samples matched this job"


@pytest.mark.asyncio
async def test_run_fine_tuning_job_prepares_external_provider_job():
    job = _job(provider="runpod")
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with (
        patch("spectra_worker.training_jobs.async_session_maker", return_value=_SessionContext(session)),
        patch("spectra_worker.training_jobs.export_dataset", new=AsyncMock(return_value=[{"input": "i"}])),
    ):
        result = await run_fine_tuning_job("job-1")

    assert result == {"status": "prepared", "job_id": "job-1", "sample_count": 1}
    assert job.status == "prepared"
    assert job.metrics["mode"] == "external_provider_ready"
    assert "api_key" in job.metrics["provider_config_fields"]
