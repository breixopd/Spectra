"""
Targets API Router.

Endpoints for managing assessment targets (IPs, domains, URLs).
Provides CRUD operations and finding associations.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import check_resource_owner, check_target_limit, get_current_active_user
from app.api.schemas import FindingResponse, PaginatedResponse, TargetCreate, TargetResponse, TargetUpdate
from app.core.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.repositories.finding import FindingRepository
from app.repositories.target import TargetRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/targets", tags=["Targets"])


# --- Endpoints ---


@router.post(
    "",
    response_model=TargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create target",
    description="Register a new assessment target (IP, CIDR, domain, or URL).",
)
async def create_target(
    target_in: TargetCreate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
) -> TargetResponse:
    """Create a new target."""
    await check_target_limit(_current_user, db)

    repo = TargetRepository(db)

    # Check if exists for this user
    existing = await repo.find_one_by(address=target_in.address, user_id=str(_current_user.id))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target with this address already exists",
        )

    target = await repo.create(
        address=target_in.address,
        description=target_in.description,
        status=target_in.status,
        os=target_in.os,
        user_id=str(_current_user.id),
    )
    await db.commit()

    return TargetResponse(
        id=target.id,
        address=target.address,
        description=target.description,
        status=target.status,
        os=target.os,
        created_at=target.created_at.isoformat(),
    )


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List targets",
    description="Retrieve all targets for the authenticated user. Superusers see all targets.",
)
async def list_targets(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> PaginatedResponse:
    """List all targets.

    Pagination: max 100 items per page.
    """
    repo = TargetRepository(db)

    # User isolation
    filters: dict = {}
    if not _current_user.is_superuser:
        filters["user_id"] = str(_current_user.id)

    total = await repo.count(**filters)
    skip = (page - 1) * per_page

    if filters:
        targets = await repo.find_many_by(skip=skip, limit=min(per_page, MAX_PAGE_SIZE), **filters)
    else:
        targets = await repo.get_all(skip=skip, limit=min(per_page, MAX_PAGE_SIZE))

    items = [
        TargetResponse(
            id=t.id,
            address=t.address,
            description=t.description,
            status=t.status,
            os=t.os,
            created_at=t.created_at.isoformat(),
        )
        for t in targets
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get(
    "/{target_id}",
    response_model=TargetResponse,
    summary="Get target",
    description="Retrieve a single target by its ID.",
)
async def get_target(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> TargetResponse:
    """Get a target by ID."""
    repo = TargetRepository(db)
    target = await repo.get_by_id(target_id)

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    check_resource_owner(target, _current_user, "target")

    return TargetResponse(
        id=target.id,
        address=target.address,
        description=target.description,
        status=target.status,
        os=target.os,
        created_at=target.created_at.isoformat(),
    )


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete target",
    description="Permanently delete a target and disassociate its findings.",
)
async def delete_target(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
) -> None:
    """Delete a target."""
    repo = TargetRepository(db)
    target = await repo.get_by_id(target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    check_resource_owner(target, _current_user, "target")
    await repo.delete(target_id)
    await db.commit()


@router.patch(
    "/{target_id}",
    response_model=TargetResponse,
    summary="Update target",
    description="Partially update a target's fields such as description, status, or OS.",
)
async def update_target(
    target_id: str,
    target_in: TargetUpdate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> TargetResponse:
    """Update a target."""
    repo = TargetRepository(db)

    # Verify ownership first
    existing = await repo.get_by_id(target_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    check_resource_owner(existing, _current_user, "target")

    # Filter out None values
    update_data = target_in.model_dump(exclude_unset=True)

    updated_target = await repo.update(target_id, **update_data)

    if not updated_target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    await db.commit()

    return TargetResponse(
        id=updated_target.id,
        address=updated_target.address,
        description=updated_target.description,
        status=updated_target.status,
        os=updated_target.os,
        created_at=updated_target.created_at.isoformat(),
    )


@router.get(
    "/{target_id}/findings",
    response_model=list[FindingResponse],
    summary="List target findings",
    description="Retrieve all security findings associated with a specific target.",
)
async def get_target_findings(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> list[FindingResponse]:
    """Get all findings for a specific target."""
    # Verify target exists and user owns it
    target_repo = TargetRepository(db)
    target = await target_repo.get_by_id(target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    check_resource_owner(target, _current_user, "target")

    finding_repo = FindingRepository(db)
    findings = await finding_repo.find_many_by(target_id=target_id)

    return [
        FindingResponse(
            id=f.id,
            title=f.title,
            description=f.description,
            severity=f.severity,
            status=f.status,
            tool_source=f.tool_source,
            created_at=f.created_at.isoformat(),
        )
        for f in findings
    ]


class BulkTargetItem(BaseModel):
    """Single target in a bulk import."""

    address: str
    description: str = ""


class BulkImportRequest(BaseModel):
    """Request body for bulk importing targets (max 500)."""

    targets: list[BulkTargetItem] = Field(..., max_length=500)


class BulkImportResponse(BaseModel):
    """Response for bulk import."""

    imported: int
    skipped: int
    errors: list[str]


@router.post(
    "/bulk-import",
    response_model=BulkImportResponse,
    summary="Bulk import targets",
    description="Import up to 500 targets at once. Duplicates are skipped.",
)
async def bulk_import_targets(
    request: BulkImportRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
) -> BulkImportResponse:
    """Import multiple targets at once."""
    repo = TargetRepository(db)
    imported = 0
    skipped = 0
    errors: list[str] = []

    for item in request.targets:
        addr = item.address.strip()
        if not addr:
            continue
        try:
            existing = await repo.find_one_by(address=addr, user_id=str(_current_user.id))
            if existing:
                skipped += 1
                continue
            await repo.create(
                address=addr,
                description=item.description,
                status="pending",
                os="Unknown",
                user_id=str(_current_user.id),
            )
            imported += 1
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Bulk import failed for target %s: %s", addr, e)
            errors.append(f"{addr}: invalid data format")

    await db.commit()
    return BulkImportResponse(imported=imported, skipped=skipped, errors=errors)


class BulkDeleteRequest(BaseModel):
    """Request body for bulk deleting targets."""

    target_ids: list[str]


class BulkDeleteResponse(BaseModel):
    """Response for bulk delete."""

    deleted: int


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_targets(
    request: BulkDeleteRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
) -> BulkDeleteResponse:
    """Bulk delete targets."""
    if len(request.target_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 targets per batch",
        )

    repo = TargetRepository(db)
    deleted_count = 0
    for tid in request.target_ids:
        target = await repo.get_by_id(tid)
        if not target:
            continue
        check_resource_owner(target, _current_user, "target")
        if await repo.delete(tid):
            deleted_count += 1
    await db.commit()

    return BulkDeleteResponse(deleted=deleted_count)
