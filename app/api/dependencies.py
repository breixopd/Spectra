"""
FastAPI Dependencies.

Provides dependency injection for database sessions and repositories.
Follows the Dependency Inversion Principle (DIP) from SOLID.
"""

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import decode_token
from app.models.plan import ApiKey
from app.models.user import User

logger = logging.getLogger("spectra.api.dependencies")

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
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        logger.warning("JWT validation failed")
        raise credentials_exception from exc

    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("User not found for token subject=%s", username)
        raise credentials_exception
    logger.debug("Authenticated user=%s", user.username)
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current user and verify they are active.
    """
    if not current_user.is_active:
        logger.warning("Inactive user attempted access user=%s", current_user.username)
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


async def _authenticate_api_key(raw_key: str, session: AsyncSession) -> User:
    """Validate an API key and return the associated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
    prefix = raw_key[:8]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    stmt = select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.is_active.is_(True))
    result = await session.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None or api_key.key_hash != key_hash:
        raise credentials_exception

    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        raise credentials_exception

    # Update last_used_at
    api_key.last_used_at = datetime.now(UTC)
    await session.commit()

    # Fetch the owning user
    user_stmt = select(User).where(User.id == api_key.user_id)
    user_result = await session.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_user_from_token_or_api_key(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Authenticate via JWT token OR API key header."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await _authenticate_api_key(api_key, session)

    # Fall back to JWT
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user = await get_current_user(token=token, session=session)
        return await get_current_active_user(current_user=user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (Bearer token or X-API-Key header)",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Plan enforcement helpers
# ---------------------------------------------------------------------------


def _is_admin_user(user: User) -> bool:
    """Return True if the user is an admin or superuser."""
    return user.is_superuser or user.role == "admin"


async def _get_user_plan(user: User, session: AsyncSession):
    """Fetch the Plan for a user, or None."""
    if not user.plan_id:
        return None
    from app.models.plan import Plan

    result = await session.execute(select(Plan).where(Plan.id == user.plan_id))
    return result.scalar_one_or_none()


async def check_mission_limit(user: User, session: AsyncSession) -> None:
    """Raise 429 if user has hit their plan's concurrent mission limit."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if not plan or not plan.max_concurrent_missions:
        return
    from app.models.mission import Mission

    active_count = (
        await session.execute(
            select(func.count(Mission.id)).where(
                Mission.user_id == str(user.id),
                Mission.status.in_(["created", "running", "paused"]),
            )
        )
    ).scalar() or 0
    if active_count >= plan.max_concurrent_missions:
        raise HTTPException(
            status_code=429,
            detail=f"Plan limit reached: max {plan.max_concurrent_missions} concurrent missions",
        )


async def check_target_limit(user: User, session: AsyncSession) -> None:
    """Raise 429 if user has hit their plan's target limit."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if not plan or not plan.max_targets:
        return
    from app.models.target import Target

    count = (
        await session.execute(
            select(func.count(Target.id)).where(Target.user_id == str(user.id))
        )
    ).scalar() or 0
    if count >= plan.max_targets:
        raise HTTPException(
            status_code=429,
            detail=f"Plan limit reached: max {plan.max_targets} targets",
        )


async def check_feature_allowed(user: User, session: AsyncSession, feature: str) -> None:
    """Raise 403 if a feature is disabled in the user's plan."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if not plan or not plan.features:
        return
    if not plan.features.get(feature, True):
        raise HTTPException(
            status_code=403,
            detail=f"Feature '{feature}' not available on your plan",
        )


async def require_mission_quota(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """Dependency that checks mission quota before allowing creation.

    Admin users bypass quota checks. Raises 429 if exceeded.
    """
    if _is_admin_user(current_user):
        return current_user

    from app.services.billing.quota_enforcement import QuotaService

    await QuotaService.check_mission_quota(str(current_user.id), db)
    return current_user


async def enforce_api_rate_limit(
    user: User = Depends(get_current_active_user),
) -> User:
    """Check and record API usage against the user's plan quota.

    Raises 429 if the hourly API request limit is exceeded.
    Returns the authenticated user on success.
    """
    if _is_admin_user(user):
        return user

    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()
    within_limit, current, maximum = await tracker.check_rate_limit(
        str(user.id), "api_requests"
    )
    if not within_limit and maximum > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Plan API rate limit exceeded: {current}/{maximum} requests this hour",
        )

    await tracker.record_api_request(str(user.id))
    return user


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
        payload = decode_token(token)
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
