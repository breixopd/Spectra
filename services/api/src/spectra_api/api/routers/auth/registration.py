"""System setup / registration endpoints."""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.schemas.auth import UserResponse
from spectra_api.api.schemas.system import SystemSetupRequest
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_common.config import get_settings
from spectra_persistence.database import get_async_session
from spectra_persistence.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

_INITIAL_SETUP_LOCK_ID = 6003372239554597200


def _verify_setup_token(request: Request, setup_in: SystemSetupRequest) -> None:
    """Require the operator-provided first-run token in production."""
    settings = get_settings()
    expected = settings.SPECTRA_SETUP_TOKEN.get_secret_value()
    supplied = request.headers.get("X-Spectra-Setup-Token") or setup_in.setup_token or ""
    production_like = settings.APP_ENV.lower() in {"production", "prod"} and not settings.DEBUG
    if not expected:
        if production_like:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Initial setup is locked until an enrollment token is configured.",
            )
        return
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid setup enrollment token.")


@router.post("/setup", response_model=UserResponse)
@limiter.limit(RateLimits.SETUP)
async def setup_admin_user(
    request: Request,  # Required by rate limiter
    response: Response,  # Required by rate limiter for headers
    setup_in: SystemSetupRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create the initial admin user and configure system settings.
    Only allowed if no users exist in the database.
    """
    _ = request  # Used by rate limiter decorator
    _verify_setup_token(request, setup_in)
    # Serialize the check-and-create transaction across API replicas.  The
    # transaction-scoped lock is released automatically on commit/rollback.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _INITIAL_SETUP_LOCK_ID},
    )

    # Check for users only after owning the setup lock. A concurrent request
    # blocks here and observes the first committed administrator.
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Users exist.",
        )

    from spectra_api.services.system.setup import SystemSetupService

    setup_service = SystemSetupService(session)
    user = await setup_service.perform_setup(setup_in)

    return user


@router.get(
    "/setup/status",
    summary="Check setup status",
    description="Returns whether the initial admin setup has been completed.",
)
async def check_setup_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Check if the system is already set up."""
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    is_setup = result.scalar_one_or_none() is not None
    return {"is_setup": is_setup}
