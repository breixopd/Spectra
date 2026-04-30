"""Admin content management — reviews, changelogs, legal pages."""

import logging
from collections.abc import Callable

import nh3
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import limiter
from app.core.database import get_async_session
from app.models.infrastructure import SystemContent
from app.models.user import User
from app.utils.html_sanitization import is_legal_content_type, sanitize_legal_html
from spectra_api.authz import Permission, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin - Content"])

SAFE_CONTENT_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "u",
    "ul",
}
SAFE_CONTENT_ATTRIBUTES = {
    "a": {"href", "target", "title"},
}
def _sanitize_html_fragment(html: str) -> str:
    return nh3.clean(
        html,
        tags=SAFE_CONTENT_TAGS,
        attributes=SAFE_CONTENT_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )
def _sanitize_content_value(value, sanitizer: Callable[[str], str] = _sanitize_html_fragment):
    if isinstance(value, dict):
        return {key: _sanitize_content_value(item, sanitizer) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_content_value(item, sanitizer) for item in value]
    if isinstance(value, str):
        return sanitizer(value)
    return value
def _sanitize_managed_content(content_type: str, value):
    sanitizer = sanitize_legal_html if is_legal_content_type(content_type) else _sanitize_html_fragment
    return _sanitize_content_value(value, sanitizer)
class ContentCreate(BaseModel):
    content_type: str
    title: str | None = None
    content: dict
    is_active: bool = True
    sort_order: int = 0
class ContentUpdate(BaseModel):
    title: str | None = None
    content: dict | None = None
    is_active: bool | None = None
    sort_order: int | None = None
@router.get("/api/admin/content")
async def list_content(
    content_type: str | None = None,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    query = select(SystemContent).order_by(SystemContent.sort_order)
    if content_type:
        query = query.where(SystemContent.content_type == content_type)
    result = await session.execute(query)
    items = result.scalars().all()
    return [
        {
            "id": item.id,
            "content_type": item.content_type,
            "title": item.title,
            "content": item.content,
            "is_active": item.is_active,
            "sort_order": item.sort_order,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in items
    ]
@router.post("/api/admin/content", status_code=201)
@limiter.limit("30/minute")
async def create_content(
    request: Request,
    body: ContentCreate,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    item = SystemContent(
        content_type=body.content_type,
        title=body.title,
        content=_sanitize_managed_content(body.content_type, body.content),
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "status": "created"}
@router.put("/api/admin/content/{content_id}")
@limiter.limit("30/minute")
async def update_content(
    request: Request,
    content_id: str,
    body: ContentUpdate,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(select(SystemContent).where(SystemContent.id == content_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    if body.title is not None:
        item.title = body.title
    if body.content is not None:
        item.content = _sanitize_managed_content(item.content_type, body.content)
    if body.is_active is not None:
        item.is_active = body.is_active
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    await session.commit()
    return {"id": item.id, "status": "updated"}
@router.delete("/api/admin/content/{content_id}")
@limiter.limit("30/minute")
async def delete_content(
    request: Request,
    content_id: str,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(select(SystemContent).where(SystemContent.id == content_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    await session.delete(item)
    await session.commit()
    return {"status": "deleted"}
