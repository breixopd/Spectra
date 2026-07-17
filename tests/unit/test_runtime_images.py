from pathlib import Path


def test_scheduler_image_contains_postgresql_backup_client() -> None:
    dockerfile = Path("deploy/docker/Dockerfile.scheduler").read_text()

    assert "postgresql-client" in dockerfile
