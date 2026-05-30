"""Storage monitoring for S3/Garage and local disk.

Checks bucket health, disk usage, and alerts when thresholds are exceeded.
"""

import logging
import shutil
import time
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class StorageMonitor:
    """Monitor S3 and local storage health with alert dedup."""

    _alert_cooldown: dict[str, float] = {}
    ALERT_COOLDOWN_SECS = 600  # 10 min between repeated alerts

    @classmethod
    async def check_s3_health(cls, storage_service) -> dict:
        """Check S3/Garage bucket health and report metrics."""
        try:
            health = await storage_service.health_check()
            return {
                "status": "healthy" if health else "unhealthy",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error("S3 health check failed: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def check_disk_usage(cls, path: str = "/") -> dict:
        """Check disk usage for a given path."""
        try:
            usage = shutil.disk_usage(path)
            pct_used = (usage.used / usage.total) * 100
            return {
                "path": path,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "pct_used": round(pct_used, 1),
            }
        except Exception as e:
            logger.error("Disk usage check failed for %s: %s", path, e)
            return {"path": path, "error": str(e)}

    @classmethod
    def should_alert(cls, key: str) -> bool:
        """Check if enough time has passed since last alert (dedup)."""
        now = time.monotonic()
        last = cls._alert_cooldown.get(key, 0)
        if now - last > cls.ALERT_COOLDOWN_SECS:
            cls._alert_cooldown[key] = now
            return True
        return False

    @classmethod
    async def get_full_status(cls, storage_service=None, data_root: str = "/data") -> dict:
        """Get comprehensive storage status for admin dashboard."""
        result = {
            "root_disk": cls.check_disk_usage("/"),
            "data_disk": cls.check_disk_usage(data_root),
        }
        if storage_service:
            result["s3"] = await cls.check_s3_health(storage_service)
        return result
