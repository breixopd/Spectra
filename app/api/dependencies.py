"""
FastAPI Dependencies.

Provides dependency injection for database sessions and repositories.
Follows the Dependency Inversion Principle (DIP) from SOLID.
"""

from datetime import datetime, timezone

UTC = timezone.utc
from typing import TYPE_CHECKING, Any, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker, get_async_session
from app.core.security import decode_token
from app.models.user import User

if TYPE_CHECKING:
    from app.repositories.exploit import ExploitRepository
    from app.repositories.finding import FindingRepository
    from app.repositories.target import TargetRepository

logger = __import__("logging").getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def _decode_access_payload(token: str) -> dict[str, Any] | None:
    """Decode a JWT and return only valid, non-pending access-token payloads."""
    try:
        payload = decode_token(token)
    except (JWTError, OSError, RuntimeError, ValueError):
        logger.debug("Access token decode failed", exc_info=True)
        return None

    if payload.get("type") != "access":
        return None
    if payload.get("mfa_pending"):
        return None
    if not payload.get("sub"):
        return None
    return payload


async def _load_active_user_from_payload(payload: dict[str, Any]) -> User | None:
    """Load the active user for a token payload and enforce DB-backed invalidation."""
    async with async_session_maker() as session:
        return await _load_active_user_from_payload_with_session(payload, session)


async def _load_active_user_from_payload_with_session(
    payload: dict[str, Any],
    session: AsyncSession,
) -> User | None:
    """Load the active user for a token payload using an existing session."""
    username = payload.get("sub")
    if not username:
        return None

    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        return None

    if user.invalidated_before:
        token_iat = payload.get("iat")
        if not token_iat:
            return None
        token_issued_at = datetime.fromtimestamp(token_iat, tz=UTC)
        if token_issued_at < user.invalidated_before:
            return None

    return user


def _extract_request_token(request: Request) -> tuple[str | None, str | None]:
    """Return the preferred request token and its source."""
    auth_header = request.headers.get("authorization", "")
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip(), "header"

    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token, "cookie"

    return None, None


def get_ui_user(request: Request) -> dict | None:
    """Extract and validate user from cookie. Returns None if not authenticated."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return _decode_access_payload(token)


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
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
    resolved_token, _source = _extract_request_token(request)
    if token and _source != "header":
        resolved_token, _source = token, "header"

    if not resolved_token:
        raise credentials_exception

    payload = _decode_access_payload(resolved_token)
    if payload is None:
        raise credentials_exception

    user = await _load_active_user_from_payload_with_session(payload, session)
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


def check_resource_owner(resource, user, resource_name: str = "resource") -> None:
    """Raise 403 if *user* does not own *resource* (superusers bypass)."""
    if user.is_superuser:
        return
    if isinstance(resource, dict):
        owner_id = resource.get("owner_id") or resource.get("user_id")
    else:
        owner_id = getattr(resource, "user_id", None)
    if owner_id != str(user.id):
        raise HTTPException(status_code=403, detail=f"Not authorized to access this {resource_name}")


async def get_target_repository(
    session: AsyncSession = Depends(get_async_session),
) -> "TargetRepository":
    """Get TargetRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured TargetRepository.
    """
    from app.repositories.target import TargetRepository

    return TargetRepository(session)


async def get_finding_repository(
    session: AsyncSession = Depends(get_async_session),
) -> "FindingRepository":
    """Get FindingRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured FindingRepository.
    """
    from app.repositories.finding import FindingRepository

    return FindingRepository(session)


async def get_exploit_repository(
    session: AsyncSession = Depends(get_async_session),
) -> "ExploitRepository":
    """Get ExploitRepository instance.

    Args:
        session: Async database session.

    Returns:
        Configured ExploitRepository.
    """
    from app.repositories.exploit import ExploitRepository

    return ExploitRepository(session)


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


async def enforce_api_rate_limit(
    user: User = Depends(get_current_active_user),
) -> User:
    """Check and record API usage against the user's plan quota.

    Raises 429 with Retry-After header if the hourly API request limit is exceeded.
    Returns the authenticated user on success.
    """
    if _is_admin_user(user):
        return user

    from app.services.billing.quota_enforcer import QuotaEnforcer
    from app.services.billing.usage_tracker import UsageTracker

    enforcer = QuotaEnforcer()
    allowed, reason = await enforcer.check_api_quota(str(user.id))
    if not allowed:
        retry_after = await enforcer.seconds_until_api_reset()
        raise HTTPException(
            status_code=429,
            detail=reason,
            headers={"Retry-After": str(retry_after)},
        )

    tracker = UsageTracker()
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
    if not token:
        return None

    payload = _decode_access_payload(token)
    if payload is None:
        return None

    return await _load_active_user_from_payload(payload)
