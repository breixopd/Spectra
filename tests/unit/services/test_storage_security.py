"""Tests for storage service S3 configuration requirements."""

from unittest.mock import MagicMock, patch

import pytest


class TestStorageS3Required:
    """Test that StorageService raises clearly when S3 is not configured."""

    def test_no_endpoint_raises_runtime_error(self):
        from spectra_platform.services.storage.service import StorageService

        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            mock_settings.S3_ACCESS_KEY = MagicMock()
            mock_settings.S3_SECRET_KEY = MagicMock()
            with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
                StorageService()

    def test_missing_access_key_raises_runtime_error(self):
        from spectra_platform.services.storage.service import StorageService

        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = "http://garage:3900"
            mock_settings.S3_ACCESS_KEY = MagicMock()
            mock_settings.S3_ACCESS_KEY.get_secret_value.return_value = ""
            mock_settings.S3_SECRET_KEY = MagicMock()
            mock_settings.S3_SECRET_KEY.get_secret_value.return_value = "secret"
            with pytest.raises(RuntimeError, match="S3_ACCESS_KEY"):
                StorageService()

    def test_missing_secret_key_raises_runtime_error(self):
        from spectra_platform.services.storage.service import StorageService

        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = "http://garage:3900"
            mock_settings.S3_ACCESS_KEY = MagicMock()
            mock_settings.S3_ACCESS_KEY.get_secret_value.return_value = "key"
            mock_settings.S3_SECRET_KEY = MagicMock()
            mock_settings.S3_SECRET_KEY.get_secret_value.return_value = ""
            with pytest.raises(RuntimeError, match="S3_SECRET_KEY"):
                StorageService()

    def test_is_s3_always_true(self, mock_storage_for_unit_tests):
        """StorageService.is_s3 is always True — local mode has been removed."""
        # The autouse mock_storage_for_unit_tests fixture provides the singleton
        # and sets is_s3=True, confirming local mode no longer exists.
        assert mock_storage_for_unit_tests.is_s3 is True

    def test_error_message_is_actionable(self):
        """Error message should tell the admin exactly what to set."""
        from spectra_platform.services.storage.service import StorageService

        with patch("spectra_platform.core.config.settings") as mock_settings:
            mock_settings.S3_ENDPOINT_URL = ""
            mock_settings.S3_ACCESS_KEY = MagicMock()
            mock_settings.S3_SECRET_KEY = MagicMock()
            try:
                StorageService()
                pytest.fail("Should have raised RuntimeError")
            except RuntimeError as e:
                msg = str(e)
                assert "S3_ENDPOINT_URL" in msg
                assert "S3_ACCESS_KEY" in msg
                assert "S3_SECRET_KEY" in msg
