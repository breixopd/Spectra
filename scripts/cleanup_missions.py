#!/usr/bin/env python3
"""Clean up missions and cached data while preserving config."""

import asyncio
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def cleanup_cache():
    """Clean up cache entries except config keys."""
    try:
        from sqlalchemy import delete

        from app.core.database import get_async_session
        from app.models.infrastructure import CacheEntry

        async for session in get_async_session():
            try:
                result = await session.execute(delete(CacheEntry))
                await session.commit()
                print(f"Deleted {result.rowcount} cache entries")
            except Exception as e:
                print(f"Cache cleanup error: {e}")
                await session.rollback()
            finally:
                await session.close()
            break
    except Exception as e:
        print(f"Cache cleanup failed: {e}")


async def cleanup_database():
    """Clean up mission-related database entries while preserving users and config."""
    try:
        from sqlalchemy import delete

        from app.core.database import get_async_session
        from app.models.finding import Finding
        from app.models.mission import Mission

        async for session in get_async_session():
            try:
                # Delete findings first (foreign key constraint)
                await session.execute(delete(Finding))
                print("Deleted all findings")

                # Delete missions
                await session.execute(delete(Mission))
                print("Deleted all missions")

                # Optionally delete targets
                # await session.execute(delete(Target))
                # print("Deleted all targets")

                await session.commit()
            except Exception as e:
                print(f"Database cleanup error: {e}")
                await session.rollback()
            finally:
                await session.close()
            break
    except Exception as e:
        print(f"Database cleanup failed: {e}")


def cleanup_reports():
    """Clean up mission reports directory."""
    reports_dir = Path("data/missions")
    if reports_dir.exists():
        # Count directories before
        mission_dirs = list(reports_dir.iterdir())
        for d in mission_dirs:
            if d.is_dir():
                shutil.rmtree(d)
        print(f"Deleted {len(mission_dirs)} mission report directories")
    else:
        print("No mission reports to delete")


async def main():
    print("Cleaning up missions and data (preserving config)...\n")

    # Clean up cache
    await cleanup_cache()

    # Clean up database
    await cleanup_database()

    # Clean up file system reports
    cleanup_reports()

    print("\nCleanup complete! Ready for fresh mission.")


if __name__ == "__main__":
    asyncio.run(main())
