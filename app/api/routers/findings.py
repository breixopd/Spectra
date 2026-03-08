"""
Findings API Router.

Endpoints for managing vulnerability findings.
Provides CRUD operations, status updates, and export endpoints.
"""

import csv
import json
from io import StringIO
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import FindingResponse
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.finding import FindingStatus, Severity
from app.models.user import User
from app.repositories.finding import FindingRepository

from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE, API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
MAX_BULK_SIZE = 100

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
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
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


# --- Export Endpoints (must be before /{finding_id} to avoid path conflicts) ---

_CSV_COLUMNS = ["id", "severity", "title", "description", "tool_source", "target_id", "cve_id", "cvss_score", "created_at"]

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_value(val: object) -> str:
    """Sanitize a value for CSV export to prevent formula injection."""
    s = str(val) if val is not None else ""
    if s and s[0] in _CSV_INJECTION_CHARS:
        return "'" + s
    return s


async def _fetch_all_findings(db: AsyncSession) -> list:
    repo = FindingRepository(db)
    return await repo.get_all(skip=0, limit=10_000)


@router.get("/export/csv")
async def export_findings_csv(
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Export all findings as CSV."""
    findings = await _fetch_all_findings(db)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for f in findings:
        writer.writerow([
            _sanitize_csv_value(f.id),
            _sanitize_csv_value(f.severity.value),
            _sanitize_csv_value(f.title),
            _sanitize_csv_value(f.description or ""),
            _sanitize_csv_value(f.tool_source),
            _sanitize_csv_value(f.target_id),
            _sanitize_csv_value(f.cve_id or ""),
            _sanitize_csv_value(f.cvss_score if f.cvss_score is not None else ""),
            _sanitize_csv_value(f.created_at.isoformat() if f.created_at else ""),
        ])

    payload = buf.getvalue().encode()

    if encrypted:
        if not password:
            raise HTTPException(status_code=400, detail="X-Export-Password header required when encrypted=true")
        from app.core.encryption import encrypt_data_with_password
        payload = encrypt_data_with_password(payload, password)
        return FastAPIResponse(
            content=payload,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=spectra_findings.csv.enc"},
        )

    return FastAPIResponse(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=spectra_findings.csv"},
    )


@router.get("/export/json")
async def export_findings_json(
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Export all findings as JSON."""
    findings = await _fetch_all_findings(db)

    data = [
        {
            "id": f.id,
            "severity": f.severity.value,
            "title": f.title,
            "description": f.description,
            "tool_source": f.tool_source,
            "target_id": f.target_id,
            "cve_id": f.cve_id,
            "cvss_score": f.cvss_score,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in findings
    ]

    payload = json.dumps(data, indent=2).encode()

    if encrypted:
        if not password:
            raise HTTPException(status_code=400, detail="X-Export-Password header required when encrypted=true")
        from app.core.encryption import encrypt_data_with_password
        payload = encrypt_data_with_password(payload, password)
        return FastAPIResponse(
            content=payload,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=spectra_findings.json.enc"},
        )

    return FastAPIResponse(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=spectra_findings.json"},
    )


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
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
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


# --- Status Transition Helpers ---

_FINDING_RESPONSE = FindingDetailResponse


def _finding_to_response(f) -> FindingDetailResponse:
    return _FINDING_RESPONSE(
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


@router.post("/{finding_id}/confirm", response_model=FindingDetailResponse)
async def confirm_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Mark a finding as confirmed/verified."""
    repo = FindingRepository(db)
    updated = await repo.update(finding_id, status=FindingStatus.VERIFIED)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    await db.commit()
    return _finding_to_response(updated)


@router.post("/{finding_id}/dismiss", response_model=FindingDetailResponse)
async def dismiss_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Dismiss a finding."""
    repo = FindingRepository(db)
    updated = await repo.update(finding_id, status=FindingStatus.DISMISSED)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    await db.commit()
    return _finding_to_response(updated)


@router.post("/{finding_id}/retest", response_model=FindingDetailResponse)
async def retest_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Request retest for a finding."""
    repo = FindingRepository(db)
    updated = await repo.update(finding_id, status=FindingStatus.RETEST_PENDING)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    await db.commit()
    return _finding_to_response(updated)


# --- Bulk Operations ---


class BulkUpdateRequest(BaseModel):
    """Request body for bulk-updating findings."""
    finding_ids: List[str] = Field(..., max_length=MAX_BULK_SIZE)
    update: FindingUpdate


class BulkUpdateResponse(BaseModel):
    """Response for bulk update."""
    updated: int


@router.post("/bulk-update", response_model=BulkUpdateResponse)
async def bulk_update_findings(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Bulk update multiple findings. Max 100 per request."""
    if len(request.finding_ids) > MAX_BULK_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_BULK_SIZE} findings per batch",
        )

    repo = FindingRepository(db)
    update_data = request.update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    updated_count = 0
    for fid in request.finding_ids:
        result = await repo.update(fid, **update_data)
        if result:
            updated_count += 1
    await db.commit()

    return BulkUpdateResponse(updated=updated_count)
