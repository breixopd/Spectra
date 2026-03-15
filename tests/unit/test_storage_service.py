"""Tests for StorageService — S3-compatible storage with local fallback."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStorageServiceInit:
    """StorageService initialization and mode selection."""

    def test_local_mode_when_s3_not_configured(self):
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            import app.services.storage.service as svc_mod

            svc_mod._storage_service = None
            svc = svc_mod.StorageService()
            assert svc.is_s3 is False
            assert svc._session is None

    def test_s3_mode_when_endpoint_configured(self):
        mock_aioboto3 = MagicMock()
        mock_aioboto3.Session.return_value = MagicMock()
        mock_boto_config = MagicMock()
        mock_client_error = type("ClientError", (Exception,), {})

        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = "http://minio:9000"
            with patch(
                "app.services.storage.service._import_s3_deps",
                return_value=(mock_aioboto3, mock_boto_config, mock_client_error),
            ):
                import app.services.storage.service as svc_mod

                svc = svc_mod.StorageService()
                assert svc.is_s3 is True
                assert svc._session is not None

    def test_lazy_import_not_called_in_local_mode(self):
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            with patch("app.services.storage.service._import_s3_deps") as mock_import:
                import app.services.storage.service as svc_mod

                svc_mod.StorageService()
                mock_import.assert_not_called()


class TestStorageServiceLocalMode:
    """Local filesystem operations."""

    @pytest.fixture
    def storage(self, tmp_path):
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            mock_settings.S3_BUCKET_MISSIONS = "spectra-missions"
            mock_settings.S3_BUCKET_SESSIONS = "spectra-sessions"
            mock_settings.S3_BUCKET_KNOWLEDGE = "spectra-knowledge"
            mock_settings.S3_BUCKET_BACKUPS = "spectra-backups"
            import app.services.storage.service as svc_mod

            svc = svc_mod.StorageService()
            # Override _local_path to use tmp_path

            def patched_local_path(bucket, key):
                return tmp_path / bucket / key

            svc._local_path = patched_local_path
            yield svc

    @pytest.mark.asyncio
    async def test_upload_download_cycle(self, storage, tmp_path):
        data = b"hello world"
        uri = await storage.upload("test-bucket", "file.txt", data)
        assert uri

        downloaded = await storage.download("test-bucket", "file.txt")
        assert downloaded == data

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, storage, tmp_path):
        await storage.upload("test-bucket", "to-delete.txt", b"temp")
        result = await storage.delete("test-bucket", "to-delete.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_true(self, storage):
        # delete on nonexistent file is still True (no error for local)
        result = await storage.delete("test-bucket", "no-such-file.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_true_for_uploaded(self, storage):
        await storage.upload("test-bucket", "exists.txt", b"data")
        assert await storage.exists("test-bucket", "exists.txt") is True

    @pytest.mark.asyncio
    async def test_exists_false_for_missing(self, storage):
        assert await storage.exists("test-bucket", "missing.txt") is False

    @pytest.mark.asyncio
    async def test_list_objects_with_prefix(self, storage, tmp_path):
        await storage.upload("mybucket", "prefix/a.txt", b"a")
        await storage.upload("mybucket", "prefix/b.txt", b"b")
        await storage.upload("mybucket", "other/c.txt", b"c")

        keys = await storage.list_objects("mybucket", prefix="prefix")
        assert len(keys) >= 2
        # All listed keys should come from the prefix directory
        for k in keys:
            assert "a.txt" in k or "b.txt" in k

    @pytest.mark.asyncio
    async def test_list_objects_empty_bucket(self, storage):
        keys = await storage.list_objects("empty-bucket")
        assert keys == []

    @pytest.mark.asyncio
    async def test_upload_file(self, storage, tmp_path):
        src = tmp_path / "source.txt"
        src.write_bytes(b"file content")
        uri = await storage.upload_file("test-bucket", "uploaded.txt", src)
        assert uri
        downloaded = await storage.download("test-bucket", "uploaded.txt")
        assert downloaded == b"file content"

    @pytest.mark.asyncio
    async def test_copy_local(self, storage):
        await storage.upload("src-bucket", "orig.txt", b"copy me")
        result = await storage.copy("src-bucket", "orig.txt", "dst-bucket", "copied.txt")
        assert result is True
        data = await storage.download("dst-bucket", "copied.txt")
        assert data == b"copy me"

    @pytest.mark.asyncio
    async def test_presigned_url_none_in_local_mode(self, storage):
        url = await storage.get_presigned_url("bucket", "key")
        assert url is None

    @pytest.mark.asyncio
    async def test_health_check_local(self, storage):
        result = await storage.health_check()
        assert result["status"] == "healthy"
        assert result["mode"] == "local"

    @pytest.mark.asyncio
    async def test_close(self, storage):
        await storage.close()
        assert storage._session is None


class TestLocalPathMapping:
    """_local_path correctly maps buckets to filesystem directories."""

    def test_missions_bucket_maps_to_data_missions(self):
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            mock_settings.S3_BUCKET_MISSIONS = "spectra-missions"
            mock_settings.S3_BUCKET_SESSIONS = "spectra-sessions"
            mock_settings.S3_BUCKET_KNOWLEDGE = "spectra-knowledge"
            mock_settings.S3_BUCKET_BACKUPS = "spectra-backups"
            import app.services.storage.service as svc_mod

            svc = svc_mod.StorageService()
            path = svc._local_path("spectra-missions", "test/file.txt")
            assert path == Path("data/missions/test/file.txt")

    def test_unknown_bucket_uses_data_prefix(self):
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            mock_settings.S3_BUCKET_MISSIONS = "spectra-missions"
            mock_settings.S3_BUCKET_SESSIONS = "spectra-sessions"
            mock_settings.S3_BUCKET_KNOWLEDGE = "spectra-knowledge"
            mock_settings.S3_BUCKET_BACKUPS = "spectra-backups"
            import app.services.storage.service as svc_mod

            svc = svc_mod.StorageService()
            path = svc._local_path("custom-bucket", "key.dat")
            assert path == Path("data/custom-bucket/key.dat")


class TestStorageServiceS3Mode:
    """S3 mode with mocked boto3 client."""

    @pytest.fixture
    def s3_storage(self):
        mock_aioboto3 = MagicMock()
        mock_session = MagicMock()
        mock_aioboto3.Session.return_value = mock_session
        mock_boto_config = MagicMock()
        mock_client_error = type("ClientError", (Exception,), {})

        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = "http://minio:9000"
            mock_settings.S3_ACCESS_KEY = MagicMock()
            mock_settings.S3_ACCESS_KEY.get_secret_value.return_value = "minioadmin"
            mock_settings.S3_SECRET_KEY = MagicMock()
            mock_settings.S3_SECRET_KEY.get_secret_value.return_value = "minioadmin"
            mock_settings.S3_REGION = "us-east-1"
            with patch(
                "app.services.storage.service._import_s3_deps",
                return_value=(mock_aioboto3, mock_boto_config, mock_client_error),
            ):
                import app.services.storage.service as svc_mod

                svc = svc_mod.StorageService()
                yield svc, mock_session

    @pytest.mark.asyncio
    async def test_upload_calls_put_object(self, s3_storage):
        svc, mock_session = s3_storage
        mock_client = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.client.return_value = mock_ctx

        # head_bucket succeeds (bucket exists)
        mock_client.head_bucket = AsyncMock()
        mock_client.put_object = AsyncMock()

        uri = await svc.upload("test-bucket", "key.txt", b"data")
        assert uri == "s3://test-bucket/key.txt"
        mock_client.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_s3_healthy(self, s3_storage):
        svc, mock_session = s3_storage
        mock_client = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.client.return_value = mock_ctx
        mock_client.list_buckets = AsyncMock(return_value={"Buckets": []})

        result = await svc.health_check()
        assert result["status"] == "healthy"
        assert result["mode"] == "s3"

    @pytest.mark.asyncio
    async def test_health_check_s3_unhealthy(self, s3_storage):
        svc, mock_session = s3_storage
        mock_client = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.client.return_value = mock_ctx
        mock_client.list_buckets = AsyncMock(side_effect=ConnectionError("connection refused"))

        result = await svc.health_check()
        assert result["status"] == "unhealthy"


class TestStorageServiceSingleton:
    """Singleton get/close functions."""

    def test_get_storage_service_creates_singleton(self):
        import app.services.storage.service as svc_mod

        svc_mod._storage_service = None
        with patch("app.services.storage.service.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            svc = svc_mod.get_storage_service()
            assert svc is not None
            svc2 = svc_mod.get_storage_service()
            assert svc is svc2
            svc_mod._storage_service = None

    @pytest.mark.asyncio
    async def test_close_storage_service(self):
        import app.services.storage.service as svc_mod

        mock_svc = AsyncMock()
        svc_mod._storage_service = mock_svc
        await svc_mod.close_storage_service()
        mock_svc.close.assert_awaited_once()
        assert svc_mod._storage_service is None

    @pytest.mark.asyncio
    async def test_close_storage_service_when_none(self):
        import app.services.storage.service as svc_mod

        svc_mod._storage_service = None
        await svc_mod.close_storage_service()  # should not raise
        assert svc_mod._storage_service is None
