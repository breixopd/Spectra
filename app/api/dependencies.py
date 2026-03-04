"""
FastAPI Dependencies.

Provides dependency injection for database sessions, Redis, and repositories.
Follows the Dependency Inversion Principle (DIP) from SOLID.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_session
from app.models.user import User
from app.repositories.exploit import ExploitRepository
from app.repositories.finding import FindingRepository
from app.repositories.target import TargetRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """
    Validate access token and get current user.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current user and verify they are active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get current user and verify they are a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user




async def get_target_repository(
    session: AsyncSession = Depends(get_async_session),
) -> TargetRepository:
    """Get TargetRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured TargetRepository.
    """
    return TargetRepository(session)


async def get_finding_repository(
    session: AsyncSession = Depends(get_async_session),
) -> FindingRepository:
    """Get FindingRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured FindingRepository.
    """
    return FindingRepository(session)


async def get_exploit_repository(
    session: AsyncSession = Depends(get_async_session),
) -> ExploitRepository:
    """Get ExploitRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured ExploitRepository.
    """
    return ExploitRepository(session)


async def validate_websocket_token(token: str | None) -> User | None:
    """
    Validate a JWT token for WebSocket authentication.

    Unlike HTTP endpoints, WebSocket can't use standard OAuth2 flow,
    so we validate the token passed as a query parameter.

    Args:
        token: JWT token from query string

    Returns:
        User if valid, None otherwise
    """
    from app.core.database import async_session_maker

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: str | None = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    # Get user from DB
    async with async_session_maker() as session:
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.is_active:
            return user

    return None
