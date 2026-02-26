"""
Findings API Router.

Endpoints for managing vulnerability findings.
Provides CRUD operations and status updates.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import FindingResponse
from app.core.database import get_async_session
from app.models.finding import FindingStatus, Severity
from app.models.user import User
from app.repositories.finding import FindingRepository

# Pagination limits
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

router = APIRouter(prefix="/findings", tags=["Findings"])


# --- Schemas ---


class FindingCreate(BaseModel):
    """Schema for creating a new finding."""

    target_id: str = Field(..., description="ID of the target")
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    severity: Severity = Severity.INFO
    status: FindingStatus = FindingStatus.POTENTIAL
    cvss_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    cve_id: Optional[str] = Field(None, max_length=20)
    tool_source: str = Field(..., max_length=100)
    evidence: Optional[dict] = None


class FindingUpdate(BaseModel):
    """Schema for updating a finding."""

    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    severity: Optional[Severity] = None
    status: Optional[FindingStatus] = None
    cvss_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    cve_id: Optional[str] = Field(None, max_length=20)


class FindingDetailResponse(FindingResponse):
    """Detailed finding response with all fields."""

    target_id: str
    cvss_score: Optional[float] = None
    cve_id: Optional[str] = None
    evidence: Optional[dict] = None


# --- Endpoints ---


@router.post(
    "", response_model=FindingDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_finding(
    finding_in: FindingCreate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Create a new finding."""
    repo = FindingRepository(db)

    finding = await repo.create(
        target_id=finding_in.target_id,
        title=finding_in.title,
        description=finding_in.description,
        severity=finding_in.severity,
        status=finding_in.status,
        cvss_score=finding_in.cvss_score,
        cve_id=finding_in.cve_id,
        tool_source=finding_in.tool_source,
        evidence=finding_in.evidence,
    )
    await db.commit()

    return FindingDetailResponse(
        id=finding.id,
        target_id=finding.target_id,
        title=finding.title,
        description=finding.description,
        severity=finding.severity.value,
        status=finding.status.value,
        cvss_score=finding.cvss_score,
        cve_id=finding.cve_id,
        tool_source=finding.tool_source,
        evidence=finding.evidence,
        created_at=finding.created_at.isoformat(),
    )


@router.get("", response_model=List[FindingDetailResponse])
async def list_findings(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    severity: Optional[Severity] = None,
    status_filter: Optional[FindingStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_async_session),
    __current_user: User = Depends(get_current_active_user),
):
    """List all findings with optional filters.

    Pagination: max 100 items per page.
    """
    repo = FindingRepository(db)

    # Build filter kwargs
    filters = {}
    if severity:
        filters["severity"] = severity
    if status_filter:
        filters["status"] = status_filter

    if filters:
        findings = await repo.find_many_by(skip=skip, limit=limit, **filters)
    else:
        findings = await repo.get_all(skip=skip, limit=limit)

    return [
        FindingDetailResponse(
            id=f.id,
            target_id=f.target_id,
            title=f.title,
            description=f.description,
            severity=f.severity.value,
            status=f.status.value,
            cvss_score=f.cvss_score,
            cve_id=f.cve_id,
            tool_source=f.tool_source,
            evidence=f.evidence,
            created_at=f.created_at.isoformat(),
        )
        for f in findings
    ]


@router.get("/{finding_id}", response_model=FindingDetailResponse)
async def get_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Get a finding by ID."""
    repo = FindingRepository(db)
    finding = await repo.get_by_id(finding_id)

    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )

    return FindingDetailResponse(
        id=finding.id,
        target_id=finding.target_id,
        title=finding.title,
        description=finding.description,
        severity=finding.severity.value,
        status=finding.status.value,
        cvss_score=finding.cvss_score,
        cve_id=finding.cve_id,
        tool_source=finding.tool_source,
        evidence=finding.evidence,
        created_at=finding.created_at.isoformat(),
    )


@router.patch("/{finding_id}", response_model=FindingDetailResponse)
async def update_finding(
    finding_id: str,
    finding_in: FindingUpdate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Update a finding."""
    repo = FindingRepository(db)

    # Filter out None values
    update_data = finding_in.model_dump(exclude_unset=True)

    updated = await repo.update(finding_id, **update_data)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    await db.commit()

    return FindingDetailResponse(
        id=updated.id,
        target_id=updated.target_id,
        title=updated.title,
        description=updated.description,
        severity=updated.severity.value,
        status=updated.status.value,
        cvss_score=updated.cvss_score,
        cve_id=updated.cve_id,
        tool_source=updated.tool_source,
        evidence=updated.evidence,
        created_at=updated.created_at.isoformat(),
    )


@router.delete("/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Delete a finding."""
    repo = FindingRepository(db)
    deleted = await repo.delete(finding_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    await db.commit()


@router.post("/{finding_id}/verify", response_model=FindingDetailResponse)
async def verify_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Mark a finding as verified."""
    repo = FindingRepository(db)

    updated = await repo.update(finding_id, status=FindingStatus.VERIFIED)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    await db.commit()

    return FindingDetailResponse(
        id=updated.id,
        target_id=updated.target_id,
        title=updated.title,
        description=updated.description,
        severity=updated.severity.value,
        status=updated.status.value,
        cvss_score=updated.cvss_score,
        cve_id=updated.cve_id,
        tool_source=updated.tool_source,
        evidence=updated.evidence,
        created_at=updated.created_at.isoformat(),
    )


@router.post("/{finding_id}/false-positive", response_model=FindingDetailResponse)
async def mark_false_positive(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Mark a finding as a false positive."""
    repo = FindingRepository(db)

    updated = await repo.update(finding_id, status=FindingStatus.FALSE_POSITIVE)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )

    return FindingDetailResponse(
        id=updated.id,
        target_id=updated.target_id,
        title=updated.title,
        description=updated.description,
        severity=updated.severity.value,
        status=updated.status.value,
        cvss_score=updated.cvss_score,
        cve_id=updated.cve_id,
        tool_source=updated.tool_source,
        evidence=updated.evidence,
        created_at=updated.created_at.isoformat(),
    )
