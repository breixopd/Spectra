"""
Public routes — landing page, pricing, self-service auth.

These routes do NOT require authentication.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.core.rate_limit import RateLimits, limiter
from app.core.security import (
    JWTError,
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.plan import Plan, Subscription
from app.models.user import User
from app.version import __version__

logger = logging.getLogger("spectra.api.public")

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_from_cookie(request: Request) -> dict | None:
    """Try to decode the JWT from the access_token cookie. Returns claims or None."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        return decode_token(token)
    except (JWTError, Exception):
        return None


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page(request: Request):
    """Landing page — redirects authenticated users to /dashboard."""
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)

    async with async_session_maker() as session:
        result = await session.execute(
            select(Plan)
            .where(Plan.is_active.is_(True))
            .order_by(Plan.sort_order)
        )
        plans = result.scalars().all()

    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "plans": plans,
            "version": __version__,
            "app_name": settings.APP_NAME,
        },
    )


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def pricing_page(request: Request):
    """Standalone pricing page — scrolls to pricing on the landing page."""
    return RedirectResponse(url="/#pricing", status_code=302)


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_page(request: Request):
    return templates.TemplateResponse("reset_password.html", {"request": request})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@router.get("/api/public/plans", tags=["Public"])
async def list_public_plans():
    """Return active plans with features for the pricing section."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Plan)
            .where(Plan.is_active.is_(True))
            .order_by(Plan.sort_order)
        )
        plans = result.scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "sort_order": p.sort_order,
            "max_concurrent_missions": p.max_concurrent_missions,
            "max_missions_per_month": p.max_missions_per_month,
            "max_targets": p.max_targets,
            "features": p.features,
            "is_default": p.is_default,
        }
        for p in plans
    ]


# --- Self-service auth schemas ---

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/api/public/register", tags=["Public"], status_code=201)
@limiter.limit("3/minute")
async def register_user(request: Request, body: RegisterRequest):
    """Self-register a new user account with the default plan."""
    async with async_session_maker() as session:
        # Check uniqueness
        existing = await session.execute(
            select(User.id).where(
                (User.username == body.username) | (User.email == body.email)
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already exists.",
            )

        # Find default plan
        default_plan = await session.execute(
            select(Plan).where(Plan.is_default.is_(True)).limit(1)
        )
        plan = default_plan.scalar_one_or_none()

        user = User(
            username=body.username,
            email=body.email,
            hashed_password=get_password_hash(body.password),
            is_active=True,
            is_superuser=False,
            role="operator",
            plan_id=plan.id if plan else None,
        )
        session.add(user)
        await session.flush()

        # Create matching Subscription row if a plan was assigned
        if plan:
            subscription = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status="active",
            )
            session.add(subscription)

        await session.commit()

    return {"detail": "Account created successfully. You can now sign in."}


@router.post("/api/public/forgot-password", tags=["Public"])
@limiter.limit("5/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Request a password reset token. In production this sends an email."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.email == body.email)
        )
        user = result.scalar_one_or_none()

    # Always return success to prevent user enumeration
    if user:
        token = create_access_token(
            data={"sub": user.username, "type": "password_reset"},
            expires_delta=timedelta(minutes=30),
        )
        # In production: send email with reset link containing this token
        logger.info("Password reset token generated for user %s", user.username)

    return {"detail": "If an account with that email exists, a reset link has been sent."}


@router.post("/api/public/reset-password", tags=["Public"])
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Reset password using a valid reset token."""
    try:
        payload = decode_token(body.token)
    except (JWTError, Exception) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        ) from exc

    if payload.get("type") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token type.",
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token.",
        )

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token.",
            )

        user.hashed_password = get_password_hash(body.new_password)
        await session.commit()

    return {"detail": "Password has been reset. You can now sign in."}
