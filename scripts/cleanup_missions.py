#!/usr/bin/env python3
"""Clean up missions and redis data while preserving config."""

import asyncio
import os
import sys
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def cleanup_redis():
    """Clean up Redis data except config keys."""
    import redis.asyncio as redis
    
    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    redis_password = os.environ.get("REDIS_PASSWORD", "spectra_redis_secret")
    
    try:
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True
        )
        
        # Get all keys
        all_keys = []
        async for key in r.scan_iter("*"):
            all_keys.append(key)
        
        # Keys to preserve (config-related)
        preserve_patterns = ["config:", "settings:", "llm:", "setup"]
        
        keys_to_delete = []
        for key in all_keys:
            should_preserve = any(pattern in key.lower() for pattern in preserve_patterns)
            if not should_preserve:
                keys_to_delete.append(key)
        
        if keys_to_delete:
            await r.delete(*keys_to_delete)
            print(f"✅ Deleted {len(keys_to_delete)} Redis keys")
        else:
            print("ℹ️  No Redis keys to delete")
        
        await r.aclose()
    except Exception as e:
        print(f"⚠️  Redis cleanup failed: {e}")


async def cleanup_database():
    """Clean up mission-related database entries while preserving users and config."""
    try:
        from sqlalchemy import delete, text
        from app.core.database import get_async_session
        from app.models.mission import Mission
        from app.models.finding import Finding
        from app.models.target import Target
        
        async for session in get_async_session():
            try:
                # Delete findings first (foreign key constraint)
                await session.execute(delete(Finding))
                print("✅ Deleted all findings")
                
                # Delete missions
                await session.execute(delete(Mission))
                print("✅ Deleted all missions")
                
                # Optionally delete targets
                # await session.execute(delete(Target))
                # print("✅ Deleted all targets")
                
                await session.commit()
            except Exception as e:
                print(f"⚠️  Database cleanup error: {e}")
                await session.rollback()
            finally:
                await session.close()
            break
    except Exception as e:
        print(f"⚠️  Database cleanup failed: {e}")


def cleanup_reports():
    """Clean up mission reports directory."""
    reports_dir = Path("reports/missions")
    if reports_dir.exists():
        # Count directories before
        mission_dirs = list(reports_dir.iterdir())
        for d in mission_dirs:
            if d.is_dir():
                shutil.rmtree(d)
        print(f"✅ Deleted {len(mission_dirs)} mission report directories")
    else:
        print("ℹ️  No mission reports to delete")


async def main():
    print("🧹 Cleaning up missions and data (preserving config)...\n")
    
    # Clean up Redis
    await cleanup_redis()
    
    # Clean up database
    await cleanup_database()
    
    # Clean up file system reports
    cleanup_reports()
    
    print("\n✨ Cleanup complete! Ready for fresh mission.")


if __name__ == "__main__":
    asyncio.run(main())
