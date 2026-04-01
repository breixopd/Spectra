"""Tests for StorageService — S3-only mode."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_s3_storage():
    """Create a StorageService with fully mocked S3 deps, patching the right target."""
    from app.services.storage.service import StorageService

    with patch("app.services.storage.service.settings") as mock_settings, \
         patch("app.services.storage.service._import_s3_deps") as mock_deps:
        mock_settings.S3_ENDPOINT_URL = "http://garage:3900"
        mock_settings.S3_ACCESS_KEY = MagicMock()
        mock_settings.S3_ACCESS_KEY.get_secret_value.return_value = "testkey"
        mock_settings.S3_SECRET_KEY = MagicMock()
        mock_settings.S3_SECRET_KEY.get_secret_value.return_value = "testsecret"
        mock_settings.S3_REGION = "us-east-1"
        mock_settings.S3_BUCKET_MISSIONS = "spectra-missions"
        mock_settings.S3_BUCKET_SESSIONS = "spectra-sessions"
        mock_settings.S3_BUCKET_KNOWLEDGE = "spectra-knowledge"
        mock_settings.S3_BUCKET_BACKUPS = "spectra-backups"
        mock_session_cls = MagicMock()
        mock_deps.return_value = (mock_session_cls, MagicMock(), Exception)
        svc = StorageService()
    svc._session = MagicMock()
    return svc


class TestStorageServiceInit:
    """Test StorageService initialization and validation."""

    def test_s3_mode_when_endpoint_configured(self):
        svc = _make_s3_storage()
        assert svc.is_s3 is True

    def test_missing_endpoint_raises_runtime_error(self):
        from app.services.storage.service import StorageService

        with patch("app.services.storage.service.settings") as s:
            s.S3_ENDPOINT_URL = ""
            s.S3_ACCESS_KEY = MagicMock()
            s.S3_SECRET_KEY = MagicMock()
            with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
                StorageService()

    def test_missing_access_key_raises(self):
        from app.services.storage.service import StorageService

        with patch("app.services.storage.service.settings") as s:
            s.S3_ENDPOINT_URL = "http://garage:3900"
            s.S3_ACCESS_KEY = MagicMock()
            s.S3_ACCESS_KEY.get_secret_value.return_value = ""
            s.S3_SECRET_KEY = MagicMock()
            s.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            with pytest.raises(RuntimeError, match="S3_ACCESS_KEY"):
                StorageService()

    def test_missing_secret_key_raises(self):
        from app.services.storage.service import StorageService

        with patch("app.services.storage.service.settings") as s:
            s.S3_ENDPOINT_URL = "http://garage:3900"
            s.S3_ACCESS_KEY = MagicMock()
            s.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            s.S3_SECRET_KEY = MagicMock()
            s.S3_SECRET_KEY.get_secret_value.return_value = ""
            with pytest.raises(RuntimeError, match="S3_SECRET_KEY"):
                StorageService()


class TestStorageServiceS3Mode:
    """Test S3 operations."""

    @pytest.fixture
    def svc(self):
        return _make_s3_storage()

    @pytest.mark.asyncio
    async def test_upload_calls_put_object(self, svc):
        mock_client = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        svc._session.client.return_value = mock_cm
        svc._buckets_ensured.add("spectra-missions")

        result = await svc.upload("spectra-missions", "test/file.bin", b"data")

        mock_client.put_object.assert_called_once_with(
            Bucket="spectra-missions", Key="test/file.bin", Body=b"data"
        )
        assert result == "s3://spectra-missions/test/file.bin"

    @pytest.mark.asyncio
    async def test_health_check_s3_healthy(self, svc):
        mock_client = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        svc._session.client.return_value = mock_cm

        with patch("app.services.storage.service.settings") as ms:
            ms.S3_ENDPOINT_URL = "http://minio:9000"
            ms.S3_REGION = "us-east-1"
            ms.S3_ACCESS_KEY = MagicMock()
            ms.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            ms.S3_SECRET_KEY = MagicMock()
            ms.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            result = await svc.health_check()

        assert result["status"] == "healthy"
        assert result["mode"] == "s3"

    @pytest.mark.asyncio
    async def test_health_check_s3_unhealthy(self, svc):
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        svc._session.client.return_value = mock_cm

        with patch("app.services.storage.service.settings") as ms:
            ms.S3_ENDPOINT_URL = "http://minio:9000"
            ms.S3_REGION = "us-east-1"
            ms.S3_ACCESS_KEY = MagicMock()
            ms.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            ms.S3_SECRET_KEY = MagicMock()
            ms.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            result = await svc.health_check()

        assert result["status"] == "unhealthy"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_delete_returns_true_on_success(self, svc):
        mock_client = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        svc._session.client.return_value = mock_cm

        with patch("app.services.storage.service.settings") as ms:
            ms.S3_ENDPOINT_URL = "http://minio:9000"
            ms.S3_REGION = "us-east-1"
            ms.S3_ACCESS_KEY = MagicMock()
            ms.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            ms.S3_SECRET_KEY = MagicMock()
            ms.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            result = await svc.delete("spectra-missions", "test/file.bin")
        assert result is True
        mock_client.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_error(self, svc):
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=OSError("disk error"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        svc._session.client.return_value = mock_cm

        with patch("app.services.storage.service.settings") as ms:
            ms.S3_ENDPOINT_URL = "http://minio:9000"
            ms.S3_REGION = "us-east-1"
            ms.S3_ACCESS_KEY = MagicMock()
            ms.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            ms.S3_SECRET_KEY = MagicMock()
            ms.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            result = await svc.delete("spectra-missions", "test/file.bin")
        assert result is False


class TestStorageServiceSingleton:
    """Test get_storage_service singleton behavior."""

    def test_get_storage_service_returns_mock_in_unit_tests(self, mock_storage_for_unit_tests):
        from app.services.storage import get_storage_service
        svc = get_storage_service()
        assert svc is mock_storage_for_unit_tests

    @pytest.mark.asyncio
    async def test_close_storage_service(self):
        from app.services.storage.service import close_storage_service
        import app.services.storage.service as svc_mod
        mock = MagicMock()
        mock.stop = AsyncMock()
        svc_mod._storage_service = mock
        await close_storage_service()
        mock.stop.assert_called_once()
        assert svc_mod._storage_service is None

    @pytest.mark.asyncio
    async def test_close_storage_service_when_none(self):
        from app.services.storage.service import close_storage_service
        import app.services.storage.service as svc_mod
        svc_mod._storage_service = None
        await close_storage_service()  # Should not raise
