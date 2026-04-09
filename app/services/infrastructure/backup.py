"""Automated database backup service — S3-native."""

import asyncio
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BackupService:
    """Creates/restores PostgreSQL backups stored in S3."""

    def __init__(self) -> None:
        from app.core.config import settings

        self.settings = settings

    @property
    def _bucket(self) -> str:
        return self.settings.S3_BUCKET_BACKUPS

    async def create_backup(self, backup_type: str = "full") -> dict:
        """pg_dump → upload to S3 → prune old. Returns metadata dict."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{timestamp}"
        s3_key = f"backups/{backup_id}.dump"

        with tempfile.TemporaryDirectory() as tmpdir:
            dump_file = Path(tmpdir) / f"{backup_id}.dump"
            try:
                parsed = urlparse(str(self.settings.DATABASE_URL.get_secret_value()).replace("+asyncpg", ""))
                env = os.environ.copy()
                env["PGPASSWORD"] = parsed.password or ""

                cmd = [
                    "pg_dump",
                    "-h",
                    parsed.hostname or "db",
                    "-p",
                    str(parsed.port or 5432),
                    "-U",
                    parsed.username or "spectra",
                    "-d",
                    (parsed.path or "/spectra").lstrip("/"),
                    "--format=custom",
                    "--compress=6",
                    "-f",
                    str(dump_file),
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

                if proc.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logger.error("pg_dump failed: %s", error_msg)
                    return {"status": "failed", "error": error_msg}

                size_bytes = dump_file.stat().st_size
                logger.info("pg_dump produced %.1f MB", size_bytes / 1024 / 1024)

            except TimeoutError:
                return {"status": "failed", "error": "pg_dump timed out after 600s"}
            except (OSError, RuntimeError, ValueError) as exc:
                return {"status": "failed", "error": str(exc)}

            # Upload to S3
            try:
                from app.services.storage.service import get_storage_service

                storage = get_storage_service()
                await storage.upload_file(self._bucket, s3_key, str(dump_file))
                logger.info("Backup uploaded to S3: %s/%s", self._bucket, s3_key)
            except Exception as exc:
                logger.error("S3 upload failed for backup %s: %s", backup_id, exc)
                return {"status": "failed", "error": "Backup upload failed"}

        # Prune old backups (after temp dir is cleaned up)
        await self._prune_old_backups()

        return {
            "status": "success",
            "backup_id": backup_id,
            "s3_key": s3_key,
            "s3_bucket": self._bucket,
            "size_bytes": size_bytes,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": backup_type,
        }

    async def restore_backup(self, backup_id: str) -> dict:
        """Download backup from S3 and restore into PostgreSQL."""
        s3_key = f"backups/{backup_id}.dump"

        from app.services.storage.service import get_storage_service

        storage = get_storage_service()

        if not await storage.exists(self._bucket, s3_key):
            return {"status": "failed", "error": f"Backup '{backup_id}' not found in S3"}

        with tempfile.TemporaryDirectory() as tmpdir:
            dump_file = Path(tmpdir) / f"{backup_id}.dump"
            try:
                await storage.download_file(self._bucket, s3_key, str(dump_file))
            except Exception as exc:
                return {"status": "failed", "error": f"S3 download failed: {exc}"}

            try:
                parsed = urlparse(str(self.settings.DATABASE_URL.get_secret_value()).replace("+asyncpg", ""))
                env = os.environ.copy()
                env["PGPASSWORD"] = parsed.password or ""

                cmd = [
                    "pg_restore",
                    "-h",
                    parsed.hostname or "db",
                    "-p",
                    str(parsed.port or 5432),
                    "-U",
                    parsed.username or "spectra",
                    "-d",
                    (parsed.path or "/spectra").lstrip("/"),
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    str(dump_file),
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

                if proc.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    if "ERROR" in error_msg:
                        return {"status": "failed", "error": error_msg}
                    logger.warning("pg_restore warnings: %s", error_msg)

                logger.info("Database restored from s3://%s/%s", self._bucket, s3_key)
                return {"status": "success", "restored_from": f"s3://{self._bucket}/{s3_key}"}

            except TimeoutError:
                return {"status": "failed", "error": "pg_restore timed out after 600s"}
            except (OSError, RuntimeError, ValueError) as exc:
                return {"status": "failed", "error": str(exc)}

    async def list_backups(self) -> list[dict]:
        """List all backups stored in S3 under the backups/ prefix."""
        from app.services.storage.service import get_storage_service

        storage = get_storage_service()
        keys = await storage.list_objects(self._bucket, prefix="backups/")
        backups = []
        for key in sorted(keys, reverse=True):
            if not key.endswith(".dump"):
                continue
            name = Path(key).stem  # backup_20260329_120000
            backups.append(
                {
                    "backup_id": name,
                    "s3_key": key,
                    "s3_uri": f"s3://{self._bucket}/{key}",
                }
            )
        return backups

    async def _prune_old_backups(self) -> None:
        """Delete S3 backup objects beyond the retention limit."""
        from app.services.storage.service import get_storage_service

        storage = get_storage_service()
        keys = sorted(await storage.list_objects(self._bucket, prefix="backups/"), reverse=True)
        dump_keys = [k for k in keys if k.endswith(".dump")]
        for old_key in dump_keys[self.settings.BACKUP_RETENTION_COUNT :]:
            deleted = await storage.delete(self._bucket, old_key)
            if deleted:
                logger.info("Pruned old backup: %s", old_key)
