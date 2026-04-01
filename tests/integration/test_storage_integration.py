"""Integration tests for StorageService with actual Garage/S3.

Requires:
- Garage container running or S3_ENDPOINT_URL configured in environment

Skip if not available.
"""

import os

import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("S3_ENDPOINT_URL"), reason="S3/Garage not configured"),
]


async def test_upload_download_roundtrip():
    """Upload data and download it back."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()

    test_data = b"integration test data"
    bucket = "spectra-test"
    key = "integration/test.txt"

    uri = await storage.upload(bucket, key, test_data)
    assert uri

    downloaded = await storage.download(bucket, key)
    assert downloaded == test_data

    await storage.delete(bucket, key)
    exists = await storage.exists(bucket, key)
    assert not exists


async def test_list_objects_with_prefix():
    """List objects filtered by prefix."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()

    bucket = "spectra-test"
    await storage.upload(bucket, "list-test/a.txt", b"a")
    await storage.upload(bucket, "list-test/b.txt", b"b")
    await storage.upload(bucket, "other/c.txt", b"c")

    keys = await storage.list_objects(bucket, prefix="list-test/")
    assert len(keys) >= 2
    assert all(k.startswith("list-test/") for k in keys)

    # Cleanup
    for k in ["list-test/a.txt", "list-test/b.txt", "other/c.txt"]:
        await storage.delete(bucket, k)


async def test_health_check():
    """Health check when S3 is configured."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    result = await storage.health_check()
    assert result["status"] == "healthy"
