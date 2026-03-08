"""
Targets API Router.

Endpoints for managing assessment targets (IPs, domains, URLs).
Provides CRUD operations and finding associations.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session

from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE, API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.api.dependencies import get_current_active_user
from app.api.schemas import FindingResponse, TargetCreate, TargetResponse, TargetUpdate
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.repositories.finding import FindingRepository
from app.repositories.target import TargetRepository

router = APIRouter(prefix="/targets", tags=["Targets"])


# --- Endpoints ---


@router.post("", response_model=TargetResponse, status_code=status.HTTP_201_CREATED)
async def create_target(
    target_in: TargetCreate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
):
    """Create a new target."""
    repo = TargetRepository(db)

    # Check if exists
    existing = await repo.find_one_by(address=target_in.address)
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


@router.get("", response_model=List[TargetResponse])
async def list_targets(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """List all targets.

    Pagination: max 100 items per page.
    """
    repo = TargetRepository(db)
    targets = await repo.get_all(skip=skip, limit=min(limit, MAX_PAGE_SIZE))

    return [
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


@router.get("/{target_id}", response_model=TargetResponse)
async def get_target(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Get a target by ID."""
    repo = TargetRepository(db)
    target = await repo.get_by_id(target_id)

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )

    return TargetResponse(
        id=target.id,
        address=target.address,
        description=target.description,
        status=target.status,
        os=target.os,
        created_at=target.created_at.isoformat(),
    )


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
):
    """Delete a target."""
    repo = TargetRepository(db)
    deleted = await repo.delete(target_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    await db.commit()


@router.patch("/{target_id}", response_model=TargetResponse)
async def update_target(
    target_id: str,
    target_in: TargetUpdate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Update a target."""
    repo = TargetRepository(db)

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


@router.get("/{target_id}/findings", response_model=List[FindingResponse])
async def get_target_findings(
    target_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Get all findings for a specific target."""
    # Verify target exists
    target_repo = TargetRepository(db)
    target = await target_repo.get_by_id(target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )

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

    targets: List[BulkTargetItem] = Field(..., max_length=500)


class BulkImportResponse(BaseModel):
    """Response for bulk import."""

    imported: int
    skipped: int
    errors: List[str]


@router.post("/bulk-import", response_model=BulkImportResponse)
async def bulk_import_targets(
    request: BulkImportRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
):
    """Import multiple targets at once."""
    repo = TargetRepository(db)
    imported = 0
    skipped = 0
    errors: List[str] = []

    for item in request.targets:
        addr = item.address.strip()
        if not addr:
            continue
        try:
            existing = await repo.find_one_by(address=addr)
            if existing:
                skipped += 1
                continue
            await repo.create(
                address=addr,
                description=item.description,
                status="pending",
                os="Unknown",
            )
            imported += 1
        except Exception as e:
            errors.append(f"{addr}: {str(e)}")

    await db.commit()
    return BulkImportResponse(imported=imported, skipped=skipped, errors=errors)


class BulkDeleteRequest(BaseModel):
    """Request body for bulk deleting targets."""

    target_ids: List[str]


class BulkDeleteResponse(BaseModel):
    """Response for bulk delete."""

    deleted: int


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_targets(
    request: BulkDeleteRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_TARGETS),
):
    """Bulk delete targets."""
    if len(request.target_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 targets per batch",
        )

    repo = TargetRepository(db)
    deleted_count = 0
    for tid in request.target_ids:
        if await repo.delete(tid):
            deleted_count += 1
    await db.commit()

    return BulkDeleteResponse(deleted=deleted_count)
