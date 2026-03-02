"""
Authentication Router.

Handles user login, setup, and token generation.
"""

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SystemSetupRequest, Token, UserResponse
from app.core.config import settings
from app.core.database import get_async_session
from app.core.events import EventType, events
from app.core.rate_limit import RateLimits, limiter
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.telemetry import telemetry
from app.models.user import User

logger = logging.getLogger("spectra.api.auth")

router = APIRouter()


@router.post("/token", response_model=Token)
@limiter.limit(RateLimits.LOGIN)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: AsyncSession = Depends(get_async_session),
):
    """
    OAuth2 compatible token login, get an access token for future requests.

    Rate limited to 5 attempts per minute per IP address.
    """
    client_ip = request.client.host if request.client else "unknown"

    # Find user
    stmt = select(User).where(User.username == form_data.username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # Always verify password even if user doesn't exist (timing-safe)
    dummy_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiLXCJzFhWMu"
    password_valid = verify_password(
        form_data.password, user.hashed_password if user else dummy_hash
    )

    if not user or not password_valid:
        logger.warning(
            "Failed login attempt for user '%s' from %s", form_data.username, client_ip
        )

        # Emit failed login event
        await events.emit(
            EventType.LOGIN_FAILED,
            source="auth",
            username=form_data.username,
            client_ip=client_ip,
        )
        telemetry.increment_counter(
            "login_failed", 1, {"reason": "invalid_credentials"}
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(
        data={"sub": user.username},
    )

    # Emit successful login event
    await events.emit(
        EventType.LOGIN_SUCCESS,
        source="auth",
        username=user.username,
        client_ip=client_ip,
    )
    telemetry.increment_counter("login_success", 1)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
@limiter.limit("5/minute")
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: str = Body(..., embed=True),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Refresh access token using a valid refresh token.
    """
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        username = payload.get("sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token subject",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check if user exists and is active
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Create new access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    # Rotate refresh token
    new_refresh_token = create_refresh_token(
        data={"sub": user.username},
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=new_refresh_token,
    )


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
    # Check if any user exists
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Users exist.",
        )

    from app.services.system.setup import SystemSetupService

    setup_service = SystemSetupService(session)
    user = await setup_service.perform_setup(setup_in)

    return user


@router.get("/setup/status")
async def check_setup_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Check if the system is already set up."""
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    is_setup = result.scalar_one_or_none() is not None
    return {"is_setup": is_setup}
