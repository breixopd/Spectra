"""Tests for BackupService — S3-native backup and restore."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.infrastructure.backup import BackupService

STORAGE_PATCH = "app.services.storage.service.get_storage_service"


def _wait_for_wrapper(recorded_timeouts: list[int | None]):
    async def _wait_for(awaitable, timeout=None):
        recorded_timeouts.append(timeout)
        return await awaitable

    return _wait_for


@pytest.fixture
def backup_svc():
    mock_settings = MagicMock()
    mock_settings.DATABASE_URL.get_secret_value.return_value = "postgresql+asyncpg://spectra:pass@db:5432/spectra"
    mock_settings.S3_BUCKET_BACKUPS = "spectra-backups"
    mock_settings.BACKUP_RETENTION_COUNT = 5

    with patch("app.services.infrastructure.backup.BackupService.__init__", return_value=None):
        svc = BackupService()
        svc.settings = mock_settings
        yield svc


@pytest.mark.asyncio
async def test_create_backup_success(backup_svc):
    """Backup should pg_dump to temp, upload to S3, return success."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0
    timeouts: list[int | None] = []

    mock_storage = MagicMock()
    mock_storage.upload_file = AsyncMock()
    mock_storage.list_objects = AsyncMock(return_value=[])
    mock_storage.delete = AsyncMock()

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", new=_wait_for_wrapper(timeouts)),
        patch(STORAGE_PATCH, return_value=mock_storage),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024
        result = await backup_svc.create_backup()

    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert "backup_id" in result
    assert timeouts == [600]
    mock_proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_backup_not_found(backup_svc):
    """Restore should fail when backup does not exist in S3."""
    mock_storage = MagicMock()
    mock_storage.exists = AsyncMock(return_value=False)

    with patch(STORAGE_PATCH, return_value=mock_storage):
        result = await backup_svc.restore_backup("backup_nonexistent")

    assert result["status"] == "failed"
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_list_backups_returns_s3_objects(backup_svc):
    """list_backups should parse S3 keys into structured backup metadata."""
    mock_storage = MagicMock()
    mock_storage.list_objects = AsyncMock(
        return_value=[
            "backups/backup_20260329_100000.dump",
            "backups/backup_20260329_120000.dump",
        ]
    )

    with patch(STORAGE_PATCH, return_value=mock_storage):
        result = await backup_svc.list_backups()

    assert len(result) == 2
    # Sorted reverse by key, so 120000 comes first
    assert result[0]["backup_id"] == "backup_20260329_120000"
    assert "s3_uri" in result[0]
    assert result[1]["backup_id"] == "backup_20260329_100000"


@pytest.mark.asyncio
async def test_create_backup_returns_failure_when_pg_dump_fails(backup_svc):
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))
    mock_proc.returncode = 1
    timeouts: list[int | None] = []

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", new=_wait_for_wrapper(timeouts)),
    ):
        result = await backup_svc.create_backup()

    assert result == {"status": "failed", "error": "permission denied"}
    assert timeouts == [600]
    mock_proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_backup_returns_failure_when_upload_fails(backup_svc):
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0
    timeouts: list[int | None] = []

    mock_storage = MagicMock()
    mock_storage.upload_file = AsyncMock(side_effect=Exception("s3 unavailable"))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", new=_wait_for_wrapper(timeouts)),
        patch(STORAGE_PATCH, return_value=mock_storage),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 2048
        result = await backup_svc.create_backup()

    assert result == {"status": "failed", "error": "Backup upload failed"}
    assert timeouts == [600]
    mock_proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_backup_returns_success_when_pg_restore_only_warns(backup_svc):
    mock_storage = MagicMock()
    mock_storage.exists = AsyncMock(return_value=True)
    mock_storage.download_file = AsyncMock()
    timeouts: list[int | None] = []

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"warning only"))
    mock_proc.returncode = 1

    with (
        patch(STORAGE_PATCH, return_value=mock_storage),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", new=_wait_for_wrapper(timeouts)),
    ):
        result = await backup_svc.restore_backup("backup_20260329_130000")

    assert result["status"] == "success"
    assert result["restored_from"].endswith("backups/backup_20260329_130000.dump")
    assert timeouts == [600]
    mock_proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_prune_old_backups_deletes_objects_past_retention(backup_svc):
    mock_storage = MagicMock()
    mock_storage.list_objects = AsyncMock(
        return_value=[
            "backups/backup_20260329_150000.dump",
            "backups/backup_20260329_140000.dump",
            "backups/backup_20260329_130000.dump",
            "backups/backup_20260329_120000.dump",
            "backups/backup_20260329_110000.dump",
            "backups/backup_20260329_100000.dump",
            "backups/backup_20260329_090000.dump",
        ]
    )
    mock_storage.delete = AsyncMock(return_value=True)

    with patch(STORAGE_PATCH, return_value=mock_storage):
        await backup_svc._prune_old_backups()

    assert mock_storage.delete.await_count == 2
    mock_storage.delete.assert_any_await("spectra-backups", "backups/backup_20260329_100000.dump")
    mock_storage.delete.assert_any_await("spectra-backups", "backups/backup_20260329_090000.dump")
