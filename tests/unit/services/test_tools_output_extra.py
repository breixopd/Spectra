from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_platform.services.tools.output import persist_output_directory, record_to_memory


@pytest.mark.asyncio
async def test_persist_output_directory(tmp_path):
    mission_id = "m1"
    output_dir = tmp_path / "scans" / "run1"
    output_dir.mkdir(parents=True)
    (output_dir / "result.json").write_text("{}")
    nested = output_dir / "nested"
    nested.mkdir()
    (nested / "file.txt").write_text("hello")

    mock_storage = AsyncMock()

    with patch("spectra_platform.services.storage.get_storage_service", return_value=mock_storage):
        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_BUCKET_MISSIONS = "missions"
            total = await persist_output_directory(mission_id, output_dir)

    assert total > 0
    assert mock_storage.upload_file.call_count == 2


@pytest.mark.asyncio
async def test_persist_output_directory_missing():
    mock_storage = AsyncMock()

    with patch("spectra_platform.services.storage.get_storage_service", return_value=mock_storage):
        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_BUCKET_MISSIONS = "missions"
            total = await persist_output_directory("m1", "/nonexistent")

    assert total == 0
    mock_storage.upload_file.assert_not_called()


@pytest.mark.asyncio
async def test_record_to_memory():
    mission = MagicMock()
    mission.user_id = "u1"
    mission.target = "1.2.3.4"
    mission.log = MagicMock()
    mission.attack_surface.services = []
    mission.directive = "test"

    result = MagicMock()
    result.success = True
    result.parsed_findings = [{"severity": "high"}]
    result.stdout = "Linux 5.4"

    mock_memory = MagicMock()

    with patch("spectra_platform.services.ai.memory.get_memory", return_value=mock_memory):
        with patch("spectra_platform.services.ai.memory.detect_os_from_output", return_value="linux"):
            record_to_memory(mission, "nmap", "1.2.3.4", {"-p": "80"}, result)

    mock_memory.record_tool_result.assert_called_once()
    mock_memory.update_target_profile.assert_called()


@pytest.mark.asyncio
async def test_record_to_memory_no_os():
    mission = MagicMock()
    mission.user_id = "u1"
    mission.target = "1.2.3.4"
    mission.log = MagicMock()
    mission.attack_surface.services = []
    mission.directive = "test"

    result = MagicMock()
    result.success = False
    result.parsed_findings = []
    result.stdout = ""

    mock_memory = MagicMock()

    with patch("spectra_platform.services.ai.memory.get_memory", return_value=mock_memory):
        with patch("spectra_platform.services.ai.memory.detect_os_from_output", return_value="unknown"):
            record_to_memory(mission, "nmap", "1.2.3.4", {}, result)

    mock_memory.record_tool_result.assert_called_once()
