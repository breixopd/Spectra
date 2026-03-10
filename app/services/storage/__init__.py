"""S3-compatible object storage service."""
from app.services.storage.service import StorageService, get_storage_service, close_storage_service

__all__ = ["StorageService", "get_storage_service", "close_storage_service"]
