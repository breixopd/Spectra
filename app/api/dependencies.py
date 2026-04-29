"""
FastAPI Dependencies.

Provides dependency injection for database sessions and repositories.
Follows the Dependency Inversion Principle (DIP) from SOLID.
"""

import uuid as _uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.advisory_locks import stable_lock_id
from app.auth.security import decode_token
from app.core.database import async_session_maker, get_async_session
from app.models.user import User
from app.services.billing.entitlements import get_user_entitlement_plan

if TYPE_CHECKING:
    from app.repositories.exploit import ExploitRepository
    from app.repositories.finding import FindingRepository
    from app.repositories.target import TargetRepository

logger = __import__("logging").getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def validate_uuid_param(value: str, param_name: str = "id") -> str:
    """Validate that a path/query parameter is a valid UUID format."""
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid {param_name} format")
    return value


async def _decode_access_payload(token: str) -> dict[str, Any] | None:
    """Decode a JWT and return only valid, non-pending access-token payloads."""
    try:
        payload = await decode_token(token)
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


async def get_ui_user(request: Request) -> dict | None:
    """Extract and validate user from cookie. Returns None if not authenticated."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return await _decode_access_payload(token)


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

    payload = await _decode_access_payload(resolved_token)
    if payload is None:
        raise credentials_exception

    user = await _load_active_user_from_payload_with_session(payload, session)
    if user is None:
        raise credentials_exception

    # Idle session timeout check
    from app.core.config import get_settings

    idle_timeout = get_settings().SESSION_IDLE_TIMEOUT_MINUTES
    if idle_timeout > 0 and isinstance(user.last_activity, datetime):
        from datetime import timedelta

        idle_limit = datetime.now(UTC) - timedelta(minutes=idle_timeout)
        if user.last_activity < idle_limit:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired due to inactivity",
            )

    # Update last_activity (throttled to every 60 seconds)
    now = datetime.now(UTC)
    if not user.last_activity or (
        isinstance(user.last_activity, datetime) and (now - user.last_activity).total_seconds() > 60
    ):
        user.last_activity = now
        await session.commit()

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current user and verify they are active.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
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
    if owner_id is None:
        raise HTTPException(status_code=403, detail="Resource access denied")
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
    if user is None:
        return False
    return getattr(user, "is_superuser", False) or getattr(user, "role", None) == "admin"


async def _get_user_plan(user: User, session: AsyncSession):
    """Fetch the Plan for a user, or None."""
    return await get_user_entitlement_plan(session, str(user.id))


async def check_mission_limit(user: User, session: AsyncSession) -> None:
    """Raise 429 if user has hit their plan's concurrent mission limit."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if plan is None:
        raise HTTPException(status_code=403, detail="No active subscription")
    if not plan.max_concurrent_missions:
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


async def check_storage_limit(user: User, session: AsyncSession) -> None:
    """Raise 429 if user has hit their plan's storage limit."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if plan is None:
        raise HTTPException(status_code=403, detail="No active subscription")
    if not plan.max_storage_mb:
        return

    from datetime import UTC

    from app.models.plan import UsageRecord

    sentinel = datetime(2000, 1, 1, tzinfo=UTC)
    rec_result = await session.execute(
        select(UsageRecord).where(
            UsageRecord.user_id == str(user.id),
            UsageRecord.period_type == "cumulative",
            UsageRecord.period_start == sentinel,
        )
    )
    record = rec_result.scalar_one_or_none()
    used = record.storage_used_mb if record else 0
    if used >= plan.max_storage_mb:
        raise HTTPException(
            status_code=429,
            detail=f"Storage limit reached: {used}/{plan.max_storage_mb} MB",
        )


async def check_target_limit(user: User, session: AsyncSession) -> None:
    """Raise 429 if user has hit their plan's target limit."""
    if _is_admin_user(user):
        return
    plan = await _get_user_plan(user, session)
    if plan is None:
        raise HTTPException(status_code=403, detail="No active subscription")
    if not plan.max_targets:
        return
    from app.models.target import Target

    count = (await session.execute(select(func.count(Target.id)).where(Target.user_id == str(user.id)))).scalar() or 0
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
    if plan is None:
        raise HTTPException(status_code=403, detail="No active subscription")
    if not plan.features:
        return
    if not plan.features.get(feature, True):
        raise HTTPException(
            status_code=403,
            detail=f"Feature '{feature}' not available on your plan",
        )


def require_feature(feature: str):
    """Return a FastAPI dependency that raises 403 if *feature* is not enabled for the current user."""

    async def _check_feature_dependency(
        user: User = Depends(get_current_active_user),
        session: AsyncSession = Depends(get_async_session),
    ) -> User:
        await check_feature_allowed(user, session, feature)
        return user

    return _check_feature_dependency


async def verify_api_quota_for_user(user: User) -> None:
    """Block with 429 when the hourly API request quota is exceeded; records each allowed call."""

    if _is_admin_user(user):
        return

    from app.services.billing.quota_enforcer import QuotaEnforcer
    from app.services.billing.usage_tracker import UsageTracker

    enforcer = QuotaEnforcer()
    tracker = UsageTracker()

    async with async_session_maker() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": stable_lock_id(f"spectra_api_quota:{user.id}")},
        )
        allowed, reason = await enforcer.check_api_quota(str(user.id), session=session)
        if not allowed:
            retry_after = await enforcer.seconds_until_api_reset()
            raise HTTPException(
                status_code=429,
                detail=reason,
                headers={"Retry-After": str(retry_after)},
            )

        await tracker.record_api_request(str(user.id), session=session)


async def enforce_api_rate_limit(
    user: User = Depends(get_current_active_user),
) -> User:
    """Check and record API usage against the user's plan quota.

    Raises 429 with Retry-After header if the hourly API request limit is exceeded.
    Returns the authenticated user on success.
    """

    await verify_api_quota_for_user(user)

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

    payload = await _decode_access_payload(token)
    if payload is None:
        return None

    return await _load_active_user_from_payload(payload)
