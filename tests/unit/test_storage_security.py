"""Tests for storage service path traversal protection."""

import pytest

from app.services.storage.service import StorageService


@pytest.fixture
def storage():
    """Create a StorageService in local (non-S3) mode."""
    svc = StorageService()
    assert not svc.is_s3
    return svc


class TestLocalPathTraversal:
    """Test _local_path rejects traversal attempts."""

    def test_normal_path_works(self, storage):
        path = storage._local_path("spectra-missions", "mission-1/report.pdf")
        assert "mission-1" in str(path)
        assert "report.pdf" in str(path)

    def test_dotdot_traversal_blocked(self, storage):
        with pytest.raises(ValueError, match="[Tt]raversal"):
            storage._local_path("spectra-missions", "../../etc/passwd")

    def test_dotdot_in_middle_blocked(self, storage):
        with pytest.raises(ValueError, match="[Tt]raversal"):
            storage._local_path("spectra-missions", "subdir/../../etc/shadow")

    def test_absolute_path_outside_base_blocked(self, storage):
        with pytest.raises(ValueError, match="[Tt]raversal"):
            storage._local_path("spectra-missions", "/etc/passwd")

    def test_nested_subdirectory_works(self, storage):
        path = storage._local_path("spectra-missions", "a/b/c/file.txt")
        assert str(path).endswith("a/b/c/file.txt")

    def test_unknown_bucket_falls_back(self, storage):
        path = storage._local_path("custom-bucket", "file.txt")
        assert "data/custom-bucket" in str(path)

    def test_null_byte_in_key(self, storage):
        """Null bytes in paths should either be blocked or result in safe resolution."""
        try:
            path = storage._local_path("spectra-missions", "file\x00.txt")
            # If it doesn't raise, the resolved path must still be inside base
            assert "data/" in str(path)
        except (ValueError, OSError):
            pass  # Blocked — correct behavior

    def test_very_long_filename(self, storage):
        """Very long filenames should not crash."""
        long_name = "a" * 500 + ".txt"
        try:
            path = storage._local_path("spectra-missions", long_name)
            assert long_name in str(path)
        except (ValueError, OSError):
            pass  # OS-level rejection is acceptable
