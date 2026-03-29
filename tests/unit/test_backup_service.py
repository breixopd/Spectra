"""Tests for BackupService — S3-native backup and restore."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.infrastructure.backup import BackupService

STORAGE_PATCH = "app.services.storage.service.get_storage_service"


@pytest.fixture
def backup_svc():
    mock_settings = MagicMock()
    mock_settings.DATABASE_URL.get_secret_value.return_value = (
        "postgresql+asyncpg://spectra:pass@db:5432/spectra"
    )
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

    mock_storage = MagicMock()
    mock_storage.upload_file = AsyncMock()
    mock_storage.list_objects = AsyncMock(return_value=[])
    mock_storage.delete = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"")), \
         patch(STORAGE_PATCH, return_value=mock_storage), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 1024
        result = await backup_svc.create_backup()

    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert "backup_id" in result


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
    mock_storage.list_objects = AsyncMock(return_value=[
        "backups/backup_20260329_100000.dump",
        "backups/backup_20260329_120000.dump",
    ])

    with patch(STORAGE_PATCH, return_value=mock_storage):
        result = await backup_svc.list_backups()

    assert len(result) == 2
    # Sorted reverse by key, so 120000 comes first
    assert result[0]["backup_id"] == "backup_20260329_120000"
    assert "s3_uri" in result[0]
    assert result[1]["backup_id"] == "backup_20260329_100000"
