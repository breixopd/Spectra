"""Admin content management — reviews, changelogs, legal pages."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.infrastructure import SystemContent
from app.models.user import User

logger = logging.getLogger("spectra.api.admin.content")

router = APIRouter(prefix="/api/admin/content", tags=["Admin - Content"])


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


@router.get("")
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


@router.post("", status_code=201)
async def create_content(
    body: ContentCreate,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    item = SystemContent(
        content_type=body.content_type,
        title=body.title,
        content=body.content,
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "status": "created"}


@router.put("/{content_id}")
async def update_content(
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
        item.content = body.content
    if body.is_active is not None:
        item.is_active = body.is_active
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    await session.commit()
    return {"id": item.id, "status": "updated"}


@router.delete("/{content_id}")
async def delete_content(
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
