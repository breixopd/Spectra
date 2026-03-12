"""Webhook Management API Router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.error_responses import internal_error, not_found
from app.core.database import get_async_session
from app.models.user import User
from app.services.webhooks.service import WebhookService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# --- Schemas ---


class WebhookCreate(BaseModel):
    url: HttpUrl = Field(..., description="Endpoint URL to receive webhook events")
    events: list[str] = Field(..., min_length=1, description="Events to subscribe to")
    secret: str | None = Field(None, description="HMAC secret for signature verification")
    description: str | None = Field(None, max_length=255)


class WebhookUpdate(BaseModel):
    url: HttpUrl | None = Field(None, description="Endpoint URL")
    events: list[str] | None = Field(None, min_length=1, description="Events to subscribe to")
    secret: str | None = Field(None, description="HMAC secret")
    description: str | None = Field(None, max_length=255)


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    description: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class WebhookTestResponse(BaseModel):
    success: bool
    status_code: int | None = None
    error: str | None = None


# --- Endpoints ---


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create webhook",
)
async def create_webhook(
    body: WebhookCreate,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    svc = WebhookService(db)
    try:
        wh = await svc.register(
            user_id=str(user.id),
            url=str(body.url),
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to create webhook for user %s", user.id)
        raise internal_error("Failed to create webhook")
    return wh


@router.get("", response_model=list[WebhookResponse], summary="List webhooks")
async def list_webhooks(
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    svc = WebhookService(db)
    try:
        return await svc.list_for_user(str(user.id))
    except Exception:
        logger.exception("Failed to list webhooks for user %s", user.id)
        raise internal_error("Failed to list webhooks")


@router.get("/{webhook_id}", response_model=WebhookResponse, summary="Get webhook")
async def get_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    svc = WebhookService(db)
    wh = await svc.get_by_id(webhook_id, str(user.id))
    if not wh:
        raise not_found("Webhook", webhook_id)
    return wh


@router.put("/{webhook_id}", response_model=WebhookResponse, summary="Update webhook")
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdate,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    svc = WebhookService(db)
    try:
        wh = await svc.update(
            webhook_id,
            str(user.id),
            url=str(body.url) if body.url is not None else None,
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to update webhook %s", webhook_id)
        raise internal_error("Failed to update webhook")
    if not wh:
        raise not_found("Webhook", webhook_id)
    return wh


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete webhook")
async def delete_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    svc = WebhookService(db)
    deleted = await svc.delete(webhook_id, str(user.id))
    if not deleted:
        raise not_found("Webhook", webhook_id)


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    summary="Test webhook",
    description="Send a test ping event to the webhook endpoint.",
)
async def test_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_user),
):
    import hashlib
    import hmac
    import json

    import httpx

    svc = WebhookService(db)
    wh = await svc.get_by_id(webhook_id, str(user.id))
    if not wh:
        raise not_found("Webhook", webhook_id)

    body = {"event": "ping", "data": {"message": "Webhook test from Spectra"}}
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if wh.secret:
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        sig = hmac.new(wh.secret.encode(), raw, hashlib.sha256).hexdigest()
        headers["X-Spectra-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(wh.url, json=body, headers=headers)
        return WebhookTestResponse(success=resp.status_code < 400, status_code=resp.status_code)
    except httpx.HTTPError as exc:
        return WebhookTestResponse(success=False, error=str(exc))
