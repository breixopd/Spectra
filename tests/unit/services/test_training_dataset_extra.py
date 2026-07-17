from unittest.mock import AsyncMock, MagicMock

import pytest

from spectra_billing.training.backends import (
    TrainingBackendDefinition,
    get_training_backend,
    list_training_backends,
    register_training_backend,
)
from spectra_billing.training.dataset import (
    create_mission_completion_sample,
    create_training_sample,
    export_dataset,
    get_dataset_stats,
    user_allows_training_data,
)


@pytest.mark.asyncio
async def test_create_training_sample():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    sample = await create_training_sample(
        mock_session,
        "m1",
        "u1",
        "tool_output",
        "input with 192.168.1.1",
        "output with password=secret",
        quality_score=0.9,
        metadata={"tool": "nmap"},
    )

    assert sample.mission_id == "m1"
    assert sample.user_id == "u1"
    assert sample.sample_type == "tool_output"
    assert "<IP_ADDR>" in sample.input_text
    assert "<REDACTED>" in sample.output_text
    assert sample.quality_score == 0.9
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_allows_training_data_requires_consent_and_unrestricted_account():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    # Tuple is (training_opt_in, processing_restricted).
    # Allowed only when opted in AND not restricted.
    mock_result.one_or_none.return_value = (True, False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    assert await user_allows_training_data(mock_session, "u1") is True

    mock_result.one_or_none.return_value = (True, True)  # opted in but restricted
    assert await user_allows_training_data(mock_session, "u1") is False

    mock_result.one_or_none.return_value = (False, False)  # not opted in
    assert await user_allows_training_data(mock_session, "u1") is False

    mock_result.one_or_none.return_value = (False, True)  # not opted in + restricted
    assert await user_allows_training_data(mock_session, "u1") is False


@pytest.mark.asyncio
async def test_create_mission_completion_sample_is_consent_gated_and_deduplicated():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    consent_result = MagicMock()
    consent_result.one_or_none.return_value = (True, False)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(side_effect=[consent_result, existing_result])
    mock_session.flush = AsyncMock()

    mission = MagicMock()
    mission.id = "m1"
    mission.user_id = "u1"
    mission.target = "192.168.1.1"
    mission.description = "Internal scan"
    mission.mission_type = "assessment"
    mission.status = "completed"

    sample = await create_mission_completion_sample(
        mock_session,
        mission,
        {"target": "192.168.1.1", "directive": "scan", "findings": [{"severity": "high"}], "tools_run": ["nmap"]},
    )

    assert sample is not None
    assert sample.sample_type == "mission_completion"
    assert sample.quality_score == 0.85
    assert "<IP_ADDR>" in sample.input_text
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_mission_completion_sample_skips_existing_sample():
    mock_session = AsyncMock()
    consent_result = MagicMock()
    consent_result.one_or_none.return_value = (True, False)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = "sample-1"
    mock_session.execute = AsyncMock(side_effect=[consent_result, existing_result])

    mission = MagicMock(id="m1", user_id="u1")

    sample = await create_mission_completion_sample(mock_session, mission, {})

    assert sample is None
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_dataset_stats():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    row = MagicMock()
    row.sample_type = "tool_output"
    row.count = 5
    row.avg_quality = 0.85
    mock_result.all.return_value = [row]
    mock_session.execute = AsyncMock(return_value=mock_result)

    stats = await get_dataset_stats(mock_session)

    assert stats["total"] == 5
    assert stats["types"]["tool_output"]["count"] == 5


@pytest.mark.asyncio
async def test_export_dataset():
    mock_session = AsyncMock()
    mock_result = MagicMock()

    sample = MagicMock()
    sample.sample_type = "tool_output"
    sample.input_text = "input"
    sample.output_text = "output"
    sample.quality_score = 0.9
    sample.metadata_ = {"tool": "nmap"}
    sample.created_at = None

    mock_result.scalars.return_value.all.return_value = [sample]
    mock_session.execute = AsyncMock(return_value=mock_result)

    data = await export_dataset(mock_session, sample_types=["tool_output"], min_quality=0.5, approved_only=True)

    assert len(data) == 1
    assert data[0]["type"] == "tool_output"
    assert data[0]["quality"] == 0.9


def test_training_backend_registry_includes_cloud_and_custom_backends():
    provider_ids = {provider["id"] for provider in list_training_backends()}

    assert {"custom", "runpod", "vast", "lambda", "modal"}.issubset(provider_ids)
    assert get_training_backend("RUNPOD").id == "runpod"


def test_training_backend_registry_allows_new_backend_registration():
    definition = TrainingBackendDefinition(
        id="demo_backend",
        name="Demo Backend",
        description="Test backend",
        status="configurable",
        config_fields=("api_key",),
    )
    register_training_backend(definition)

    try:
        assert get_training_backend("demo_backend") == definition
    finally:
        from spectra_billing.training import backends

        backends._BACKENDS.pop("demo_backend", None)


def test_training_backend_registry_rejects_duplicate_backend():
    definition = TrainingBackendDefinition(
        id="runpod",
        name="RunPod duplicate",
        description="Duplicate",
        status="configurable",
    )

    with pytest.raises(ValueError, match="already registered"):
        register_training_backend(definition)
