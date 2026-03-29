"""
Public routes — landing page, pricing, self-service auth.

These routes do NOT require authentication.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import async_session_maker
from app.core.rate_limit import limiter
from app.core.security import (
    JWTError,
    decode_token,
    get_password_hash,
)
from app.models.plan import Plan, Subscription
from app.models.user import User
from app.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["version"] = __version__

from app.core.constants import format_feature_label

templates.env.filters["feature_label"] = format_feature_label


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


def _extract_legal_html(raw: object) -> object:
    """Extract HTML content from admin-managed legal JSON envelope."""
    if isinstance(raw, dict) and "html" in raw:
        return raw["html"]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "html" in parsed:
                return parsed["html"]
        except (json.JSONDecodeError, ValueError):
            pass
    return raw


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page(request: Request):
    """Landing page — redirects authenticated users to /dashboard."""
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)

    async with async_session_maker() as session:
        result = await session.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
        plans = result.scalars().all()

        # Query real stats for landing page
        try:
            findings_result = await session.execute(text("SELECT COUNT(*) FROM findings"))
            total_findings = findings_result.scalar() or 0
            missions_result = await session.execute(text("SELECT COUNT(*) FROM missions WHERE status = 'completed'"))
            total_missions = missions_result.scalar() or 0
        except (OSError, RuntimeError, ValueError):
            logger.debug("Failed to load landing stats", exc_info=True)
            total_findings = 0
            total_missions = 0

        plugin_dir = APP_DIR.parent / "plugins"
        total_tools = len(list(plugin_dir.glob("*.json"))) if plugin_dir.exists() else 0

        stats = {
            "total_findings": f"{total_findings:,}",
            "total_missions": f"{total_missions:,}",
            "uptime": "99.9%",
            "total_tools": str(total_tools),
        }

        # Query admin-managed reviews
        try:
            reviews_result = await session.execute(
                text("SELECT content FROM system_content WHERE content_type = 'review' AND is_active = true ORDER BY sort_order")
            )
            reviews = [
                json.loads(r[0]) if isinstance(r[0], str) else r[0]
                for r in reviews_result.fetchall()
            ]
        except (ValueError, TypeError):
            logger.debug("Failed to load reviews", exc_info=True)
            reviews = []

    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "plans": plans,
            "version": __version__,
            "app_name": settings.APP_NAME,
            "stats": stats,
            "reviews": reviews,
        },
    )


@router.get("/sitemap.xml", response_class=Response, include_in_schema=False)
async def sitemap(request: Request):
    """Dynamic sitemap for public pages."""
    base = f"{request.url.scheme}://{request.url.netloc}"
    urls = [
        ("", "1.0", "monthly"),
        ("/changelog", "0.5", "weekly"),
        ("/help", "0.5", "monthly"),
        ("/docs", "0.7", "weekly"),
        ("/login", "0.3", "monthly"),
        ("/register", "0.3", "monthly"),
    ]
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for path, priority, freq in urls:
        xml_parts.append(f"  <url><loc>{base}{path}</loc><priority>{priority}</priority><changefreq>{freq}</changefreq></url>")
    xml_parts.append("</urlset>")
    return Response(content="\n".join(xml_parts), media_type="application/xml")


@router.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def status_page(request: Request):
    return templates.TemplateResponse("status.html", {
        "request": request,
        "app_name": settings.APP_NAME,
        "is_public_page": True,
    })


@router.get("/security", response_class=HTMLResponse, include_in_schema=False)
async def security_page(request: Request):
    return templates.TemplateResponse("security.html", {
        "request": request,
        "app_name": settings.APP_NAME,
        "is_public_page": True,
    })


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def pricing_page(request: Request):
    """Standalone pricing page — scrolls to pricing on the landing page."""
    return RedirectResponse(url="/#pricing", status_code=302)


@router.get("/legal/terms", response_class=HTMLResponse, include_in_schema=False)
async def legal_terms(request: Request):
    content_override = None
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                text("SELECT content FROM system_content WHERE content_type = 'legal_terms' AND is_active = true ORDER BY sort_order LIMIT 1")
            )
            row = result.fetchone()
            if row:
                content_override = _extract_legal_html(row[0])
    except (OSError, RuntimeError, ValueError):
        logger.debug("Failed to load legal terms", exc_info=True)
    return templates.TemplateResponse("legal/terms.html", {"request": request, "app_name": settings.APP_NAME, "content_override": content_override, "is_public_page": True})


@router.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
async def legal_privacy(request: Request):
    content_override = None
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                text("SELECT content FROM system_content WHERE content_type = 'legal_privacy' AND is_active = true ORDER BY sort_order LIMIT 1")
            )
            row = result.fetchone()
            if row:
                content_override = _extract_legal_html(row[0])
    except (OSError, RuntimeError, ValueError):
        logger.debug("Failed to load legal privacy", exc_info=True)
    return templates.TemplateResponse("legal/privacy.html", {"request": request, "app_name": settings.APP_NAME, "content_override": content_override, "is_public_page": True})


@router.get("/legal/cookies", response_class=HTMLResponse, include_in_schema=False)
async def legal_cookies(request: Request):
    content_override = None
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                text("SELECT content FROM system_content WHERE content_type = 'legal_cookies' AND is_active = true ORDER BY sort_order LIMIT 1")
            )
            row = result.fetchone()
            if row:
                content_override = _extract_legal_html(row[0])
    except (OSError, RuntimeError, ValueError):
        logger.debug("Failed to load legal cookies", exc_info=True)
    return templates.TemplateResponse("legal/cookie.html", {"request": request, "app_name": settings.APP_NAME, "content_override": content_override, "is_public_page": True})


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    # Block registration until setup is complete (a superuser exists)
    async with async_session_maker() as session:
        superuser_exists = await session.execute(select(User.id).where(User.is_superuser.is_(True)).limit(1))
        if not superuser_exists.scalar_one_or_none():
            return RedirectResponse(url="/setup", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_page(request: Request):
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_page(request: Request):
    if _get_user_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("reset_password.html", {"request": request})


@router.get("/changelog", response_class=HTMLResponse, include_in_schema=False)
async def changelog_page(request: Request):
    """Display changelog entries from system_content."""
    changelogs: list[dict] = []
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                text(
                    "SELECT title, content FROM system_content "
                    "WHERE content_type = 'changelog' AND is_active = true "
                    "ORDER BY sort_order DESC"
                )
            )
            changelogs = [
                {"title": r[0], "content": json.loads(r[1]) if isinstance(r[1], str) else r[1]}
                for r in result.fetchall()
            ]
    except (OSError, RuntimeError, ValueError):
        logger.debug("Failed to load changelog", exc_info=True)
    return templates.TemplateResponse(
        "changelog.html",
        {"request": request, "app_name": settings.APP_NAME, "changelogs": changelogs, "version": __version__, "is_public_page": True},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@router.get("/api/public/plans", tags=["Public"])
async def list_public_plans():
    """Return active plans with features for the pricing section."""
    async with async_session_maker() as session:
        result = await session.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
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


def _validate_password_strength(v: str) -> str:
    """Shared password strength validator."""
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit")
    return v


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


@router.post("/api/public/register", tags=["Public"], status_code=201)
@limiter.limit("3/minute")
async def register_user(request: Request, body: RegisterRequest):
    """Self-register a new user account with the default plan."""
    async with async_session_maker() as session:
        # Block registration until setup is complete (a superuser exists)
        superuser_check = await session.execute(select(User.id).where(User.is_superuser.is_(True)).limit(1))
        if not superuser_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is not available until system setup is complete.",
            )

        # Check uniqueness
        existing = await session.execute(
            select(User.id).where((User.username == body.username) | (User.email == body.email))
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already exists.",
            )

        # Find default plan
        default_plan = await session.execute(select(Plan).where(Plan.is_default.is_(True)).limit(1))
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

        from app.models.audit_log import AuditEventType
        from app.services.system.audit import log_event as audit_log_event

        await audit_log_event(
            session, AuditEventType.REGISTRATION,
            user_id=str(user.id),
            details={"username": body.username},
            request=request,
        )

        # Auto-detect: if SMTP is configured, require email verification
        if settings.smtp_configured or settings.EMAIL_VERIFICATION_ENABLED:
            user.email_verified = False
            await session.commit()

            # Send verification email
            try:
                from app.core.security import create_email_verification_token
                from app.services.email import EmailService

                token = create_email_verification_token(str(user.id))
                base_url = settings.PLATFORM_BASE_URL or str(request.base_url).rstrip("/")
                verify_url = f"{base_url}/verify-email?token={token}"

                email_svc = EmailService()
                await email_svc.send_template(
                    to=body.email,
                    template_name="email_verification",
                    subject="Verify your Spectra account",
                    username=body.username,
                    verify_url=verify_url,
                )
            except (OSError, RuntimeError, ConnectionError):
                logger.exception("Failed to send verification email to %s", body.username)

    # Send welcome email (fire-and-forget — don't block registration)
    try:
        from app.services.email import EmailService

        email_svc = EmailService()
        base_url = settings.PLATFORM_BASE_URL or "http://localhost:5000"
        await email_svc.send_template(
            to=body.email,
            template_name="welcome",
            subject="Welcome to Spectra",
            username=body.username,
            login_url=f"{base_url}/login",
        )
    except (OSError, RuntimeError, ConnectionError):
        logger.exception("Failed to send welcome email to %s", body.username)

    if settings.smtp_configured or settings.EMAIL_VERIFICATION_ENABLED:
        return {"detail": "Account created. Please check your email to verify your account before signing in."}
    return {"detail": "Account created successfully. You can now sign in."}


@router.get("/verify-email", response_class=HTMLResponse, include_in_schema=False)
async def verify_email_page(request: Request, token: str = ""):
    """Handle email verification link click."""
    from app.core.security import verify_email_verification_token

    if not token:
        return templates.TemplateResponse("verify_email.html", {
            "request": request,
            "success": False,
            "message": "Missing verification token.",
        })

    user_id = verify_email_verification_token(token)
    if not user_id:
        return templates.TemplateResponse("verify_email.html", {
            "request": request,
            "success": False,
            "message": "Invalid or expired verification link. Please register again.",
        })

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return templates.TemplateResponse("verify_email.html", {
                "request": request,
                "success": False,
                "message": "Account not found.",
            })

        if user.email_verified:
            return templates.TemplateResponse("verify_email.html", {
                "request": request,
                "success": True,
                "message": "Email already verified. You can log in.",
            })

        user.email_verified = True
        await session.commit()

    return templates.TemplateResponse("verify_email.html", {
        "request": request,
        "success": True,
        "message": "Email verified! You can now log in.",
    })
