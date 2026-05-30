"""S3-compatible object storage service."""

from spectra_storage_policy.storage.service import StorageService, close_storage_service, get_storage_service

__all__ = ["StorageService", "close_storage_service", "get_storage_service"]
