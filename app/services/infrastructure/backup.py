"""Automated database and data backup service.

Supports:
- PostgreSQL pg_dump (compressed custom format)
- S3 or local file storage for backups
- Pruning old backups based on retention count
- Restore from any backup
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("spectra.backup")


class BackupService:
    """Manages automated backups and restores."""

    def __init__(self):
        from app.core.config import get_settings

        self.settings = get_settings()
        self.backup_dir = Path("/app/data/backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(self, backup_type: str = "full") -> dict:
        """Create a database backup.

        Returns dict with backup metadata (id, path, size, timestamp).
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{timestamp}"
        dump_file = self.backup_dir / f"{backup_id}.dump"

        try:
            parsed = urlparse(
                str(self.settings.DATABASE_URL.get_secret_value()).replace("+asyncpg", "")
            )
            env = os.environ.copy()
            env["PGPASSWORD"] = parsed.password or ""

            cmd = [
                "pg_dump",
                "-h", parsed.hostname or "db",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "spectra",
                "-d", parsed.path.lstrip("/") or "spectra",
                "--format=custom",
                "--compress=6",
                "-f", str(dump_file),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error("pg_dump failed: %s", error_msg)
                return {"status": "failed", "error": error_msg}

            size_bytes = dump_file.stat().st_size if dump_file.exists() else 0

            # Upload to S3 if configured
            s3_path = None
            if self.settings.S3_ENDPOINT_URL:
                s3_path = await self._upload_to_s3(dump_file, backup_id)

            # Prune old backups
            await self._prune_old_backups()

            result = {
                "status": "success",
                "backup_id": backup_id,
                "path": str(dump_file),
                "s3_path": s3_path,
                "size_bytes": size_bytes,
                "timestamp": datetime.now(UTC).isoformat(),
                "type": backup_type,
            }
            logger.info("Backup created: %s (%.1f MB)", backup_id, size_bytes / 1024 / 1024)
            return result

        except TimeoutError:
            logger.error("Backup timed out after 600s")
            return {"status": "failed", "error": "Backup timed out"}
        except Exception as e:
            logger.error("Backup failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def restore_backup(self, backup_path: str) -> dict:
        """Restore database from a backup file."""
        path = Path(backup_path)
        if not path.exists():
            return {"status": "failed", "error": "Backup file not found"}

        # Validate the path is within the backup directory
        try:
            path.resolve().relative_to(self.backup_dir.resolve())
        except ValueError:
            return {"status": "failed", "error": "Invalid backup path"}

        try:
            parsed = urlparse(
                str(self.settings.DATABASE_URL.get_secret_value()).replace("+asyncpg", "")
            )
            env = os.environ.copy()
            env["PGPASSWORD"] = parsed.password or ""

            cmd = [
                "pg_restore",
                "-h", parsed.hostname or "db",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "spectra",
                "-d", parsed.path.lstrip("/") or "spectra",
                "--clean",
                "--if-exists",
                "--no-owner",
                backup_path,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                # pg_restore returns non-zero for warnings too
                if "ERROR" in error_msg:
                    return {"status": "failed", "error": error_msg}
                logger.warning("pg_restore warnings: %s", error_msg)

            logger.info("Backup restored from: %s", backup_path)
            return {"status": "success", "restored_from": backup_path}

        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def list_backups(self) -> list[dict]:
        """List all available backups."""
        backups = []
        for f in sorted(self.backup_dir.glob("backup_*.dump"), reverse=True):
            backups.append({
                "backup_id": f.stem,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat(),
            })
        return backups

    async def _upload_to_s3(self, file_path: Path, backup_id: str) -> str | None:
        """Upload backup to S3/MinIO."""
        try:
            from app.services.storage.service import StorageService

            storage = StorageService()
            s3_key = f"backups/{backup_id}.dump"
            with open(file_path, "rb") as f:
                await storage.upload_fileobj(f, self.settings.BACKUP_S3_BUCKET, s3_key)
            return f"s3://{self.settings.BACKUP_S3_BUCKET}/{s3_key}"
        except Exception as e:
            logger.warning("S3 backup upload failed: %s", e)
            return None

    async def _prune_old_backups(self):
        """Remove backups exceeding the retention count."""
        backups = sorted(
            self.backup_dir.glob("backup_*.dump"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in backups[self.settings.BACKUP_RETENTION_COUNT:]:
            old.unlink(missing_ok=True)
            logger.info("Pruned old backup: %s", old.name)
