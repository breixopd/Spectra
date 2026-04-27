from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.training.dataset import create_training_sample, export_dataset, get_dataset_stats


@pytest.mark.asyncio
async def test_create_training_sample():
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()

    sample = await create_training_sample(
        mock_session, "m1", "u1", "tool_output",
        "input with 192.168.1.1", "output with password=secret",
        quality_score=0.9, metadata={"tool": "nmap"}
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
