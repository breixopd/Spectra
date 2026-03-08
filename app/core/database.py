"""
Async SQLAlchemy Database Setup.

Provides async engine, session maker, and a dependency for FastAPI.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.config import settings


# --- Async Engine ---
def _configure_database_url(url: str) -> tuple[str, dict]:
    """
    Configure database URL and connection arguments.

    Handles 'sslmode' query parameter which is not supported by asyncpg directly.
    Returns: (clean_url, connect_args)
    """
    connect_args = {}

    if "sslmode" in url:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        qs = parse_qs(parsed.query)

        if "sslmode" in qs:
            ssl_mode = qs.pop("sslmode")[0]
            # Map postgres sslmode to asyncpg ssl parameter
            # allowed: disable, allow, prefer, require, verify-ca, verify-full
            if ssl_mode in ("require", "verify-ca", "verify-full"):
                connect_args["ssl"] = ssl_mode

            # Reconstruct URL without sslmode
            new_query = urlencode(qs, doseq=True)
            converted = parsed._replace(query=new_query)
            url = urlunparse(converted)

    # DEBUG: Log the connection details
    # masked_url = url
    # if "@" in url:
    #     part1, part2 = url.rsplit("@", 1)
    #     if ":" in part1:
    #         schema_user, _ = part1.rsplit(":", 1)
    #         masked_url = f"{schema_user}:***@{part2}"
    # logger.info(f"Connecting to DB: {masked_url}")
    # logger.info(f"DB Connect Args: {connect_args}")

    return url, connect_args


db_url, connect_args = _configure_database_url(settings.DATABASE_URL.get_secret_value())


engine = create_async_engine(
    db_url,
    echo=settings.DATABASE_ECHO,
    future=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# --- Session Maker ---
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
