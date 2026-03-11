#!/usr/bin/env python3
import asyncio
import os

from sqlalchemy import delete

from app.core.database import get_async_session
from app.models.user import User


async def reset_users() -> None:
    """Reset all users in the database."""
    print("Resetting users...")
    # Use SQLite for local testing if DB is not available
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./spectra.db"

    async for session in get_async_session():
        try:
            # Delete all users
            await session.execute(delete(User))
            await session.commit()
            print(
                "All users deleted. You can now visit /setup to create a new admin account."
            )
        except Exception as e:
            print(f"Error resetting users: {e}")
            await session.rollback()
        finally:
            await session.close()
        # Break after first iteration (outside finally to avoid swallowing exceptions)
        break


if __name__ == "__main__":
    asyncio.run(reset_users())
