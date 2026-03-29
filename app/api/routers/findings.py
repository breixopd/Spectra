"""
Findings API Router.

Endpoints for managing vulnerability findings.
Provides CRUD operations, status updates, and export endpoints.
"""

from __future__ import annotations

import csv
import json
import logging
from io import StringIO

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import check_resource_owner, get_current_active_user
from app.api.schemas import FindingResponse, PaginatedResponse
from app.core.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from app.core.constants import MAX_BULK_FINDINGS
from app.core.database import get_async_session
from app.core.rate_limit import RateLimits, limiter
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.finding import FindingStatus, Severity
from app.models.user import User
from app.repositories.finding import FindingRepository
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/findings", tags=["Findings"])


# --- Schemas ---


class FindingCreate(BaseModel):
    """Schema for creating a new finding."""

    target_id: str = Field(..., description="ID of the target")
    title: str = Field(..., max_length=500)
    description: str | None = None
    severity: Severity = Severity.INFO
    status: FindingStatus = FindingStatus.POTENTIAL
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)
    tool_source: str = Field(..., max_length=100)
    evidence: dict | None = None


class FindingUpdate(BaseModel):
    """Schema for updating a finding."""

    title: str | None = Field(None, max_length=500)
    description: str | None = None
    severity: Severity | None = None
    status: FindingStatus | None = None
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)


class FindingDetailResponse(FindingResponse):
    """Detailed finding response with all fields."""

    target_id: str
    cvss_score: float | None = None
    cve_id: str | None = None
    evidence: dict | None = None


_FINDING_RESPONSE = FindingDetailResponse


def _finding_to_response(finding) -> FindingDetailResponse:
    return _FINDING_RESPONSE(
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


def _finding_filters(
    current_user: User,
    *,
    severity: Severity | None = None,
    status_filter: FindingStatus | None = None,
) -> dict[str, object]:
    filters: dict[str, object] = {}
    if not current_user.is_superuser:
        filters["user_id"] = str(current_user.id)
    if severity is not None:
        filters["severity"] = severity
    if status_filter is not None:
        filters["status"] = status_filter
    return filters


def _finding_update_audit_details(finding, changed_fields: list[str]) -> dict[str, object]:
    return {
        "finding_id": finding.id,
        "target_id": finding.target_id,
        "changed_fields": changed_fields,
    }


def _finding_status_audit_details(finding, action: str) -> dict[str, str]:
    return {
        "finding_id": finding.id,
        "target_id": finding.target_id,
        "status": finding.status.value,
        "action": action,
    }


async def _get_finding_or_404(repo: FindingRepository, finding_id: str):
    finding = await repo.get_by_id(finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    return finding


async def _get_owned_finding_or_404(repo: FindingRepository, finding_id: str, current_user: User):
    finding = await _get_finding_or_404(repo, finding_id)
    check_resource_owner(finding, current_user, "finding")
    return finding


async def _update_owned_finding_status(
    repo: FindingRepository,
    finding_id: str,
    current_user: User,
    new_status: FindingStatus,
):
    await _get_owned_finding_or_404(repo, finding_id, current_user)
    return await repo.update(finding_id, status=new_status)


# --- Endpoints ---


@router.post(
    "",
    response_model=FindingDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create finding",
    description="Create a new security finding associated with a target.",
)
async def create_finding(
    finding_in: FindingCreate,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> FindingDetailResponse:
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
        user_id=str(_current_user.id),
    )
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_CREATED,
        user_id=str(_current_user.id),
        details={
            "finding_id": finding.id,
            "target_id": finding.target_id,
            "severity": finding.severity.value,
            "title": finding.title,
        },
        request=request,
    )

    return _finding_to_response(finding)


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List findings",
    description="Retrieve all findings with optional severity and status filters.",
)
@limiter.limit(RateLimits.FINDINGS_LIST)
async def list_findings(
    request: Request = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    severity: Severity | None = None,
    status_filter: FindingStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> PaginatedResponse:
    """List all findings with optional filters.

    Pagination: max 100 items per page.
    """
    repo = FindingRepository(db)
    filters = _finding_filters(_current_user, severity=severity, status_filter=status_filter)

    total = await repo.count(**filters)
    skip = (page - 1) * per_page

    if filters:
        findings = await repo.find_many_by(skip=skip, limit=per_page, **filters)
    else:
        findings = await repo.get_all(skip=skip, limit=per_page)

    items = [_finding_to_response(finding) for finding in findings]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


# --- Export Endpoints (must be before /{finding_id} to avoid path conflicts) ---

_CSV_COLUMNS = [
    "id",
    "severity",
    "title",
    "description",
    "tool_source",
    "target_id",
    "cve_id",
    "cvss_score",
    "created_at",
]

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_value(val: object) -> str:
    """Sanitize a value for CSV export to prevent formula injection."""
    s = str(val) if val is not None else ""
    if s and s[0] in _CSV_INJECTION_CHARS:
        return "'" + s
    return s


async def _fetch_all_findings(db: AsyncSession, user: User | None = None) -> list:
    repo = FindingRepository(db)
    if user and not user.is_superuser:
        return list(await repo.find_many_by(user_id=str(user.id), skip=0, limit=10_000))
    return list(await repo.get_all(skip=0, limit=10_000))


@router.get(
    "/export/csv",
    summary="Export findings as CSV",
    description="Export all findings as a CSV file. Optionally encrypt with a password.",
)
@limiter.limit(RateLimits.FINDINGS_EXPORT)
async def export_findings_csv(
    request: Request = None,
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FastAPIResponse:
    """Export all findings as CSV."""
    findings = await _fetch_all_findings(db, _current_user)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for f in findings:
        writer.writerow(
            [
                _sanitize_csv_value(f.id),
                _sanitize_csv_value(f.severity.value),
                _sanitize_csv_value(f.title),
                _sanitize_csv_value(f.description or ""),
                _sanitize_csv_value(f.tool_source),
                _sanitize_csv_value(f.target_id),
                _sanitize_csv_value(f.cve_id or ""),
                _sanitize_csv_value(f.cvss_score if f.cvss_score is not None else ""),
                _sanitize_csv_value(f.created_at.isoformat() if f.created_at else ""),
            ]
        )

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


@router.get(
    "/export/json",
    summary="Export findings as JSON",
    description="Export all findings as a JSON file. Optionally encrypt with a password.",
)
@limiter.limit(RateLimits.FINDINGS_EXPORT)
async def export_findings_json(
    request: Request = None,
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FastAPIResponse:
    """Export all findings as JSON."""
    findings = await _fetch_all_findings(db, _current_user)

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


@router.get(
    "/{finding_id}",
    response_model=FindingDetailResponse,
    summary="Get finding",
    description="Retrieve a single finding by its ID.",
)
async def get_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Get a finding by ID."""
    repo = FindingRepository(db)
    finding = await _get_owned_finding_or_404(repo, finding_id, _current_user)
    return _finding_to_response(finding)


@router.patch(
    "/{finding_id}",
    response_model=FindingDetailResponse,
    summary="Update finding",
    description="Partially update a finding's fields such as title, severity, or status.",
)
async def update_finding(
    finding_id: str,
    finding_in: FindingUpdate,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Update a finding."""
    repo = FindingRepository(db)
    await _get_owned_finding_or_404(repo, finding_id, _current_user)

    # Filter out None values
    update_data = finding_in.model_dump(exclude_unset=True)

    updated = await repo.update(finding_id, **update_data)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    await db.commit()

    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_update_audit_details(updated, sorted(update_data.keys())),
        request=request,
    )

    return _finding_to_response(updated)


@router.delete(
    "/{finding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete finding",
    description="Permanently delete a security finding.",
)
async def delete_finding(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> None:
    """Delete a finding."""
    repo = FindingRepository(db)
    existing = await _get_owned_finding_or_404(repo, finding_id, _current_user)

    details = {"finding_id": existing.id, "target_id": existing.target_id, "title": existing.title, "severity": existing.severity.value}
    await repo.delete(finding_id)
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_DELETED,
        user_id=str(_current_user.id),
        details=details,
        request=request,
    )


@router.post(
    "/{finding_id}/verify",
    response_model=FindingDetailResponse,
    summary="Verify finding",
    description="Mark a finding as verified after manual confirmation.",
)
async def verify_finding(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as verified."""
    repo = FindingRepository(db)
    updated = await _update_owned_finding_status(repo, finding_id, _current_user, FindingStatus.VERIFIED)
    await db.commit()
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update failed unexpectedly",
        )
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_status_audit_details(updated, "verify"),
        request=request,
    )

    return _finding_to_response(updated)


@router.post(
    "/{finding_id}/false-positive",
    response_model=FindingDetailResponse,
    summary="Mark false positive",
    description="Mark a finding as a false positive to exclude it from active results.",
)
async def mark_false_positive(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as a false positive."""
    repo = FindingRepository(db)
    updated = await _update_owned_finding_status(repo, finding_id, _current_user, FindingStatus.FALSE_POSITIVE)
    await db.commit()
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update failed unexpectedly",
        )
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_status_audit_details(updated, "mark_false_positive"),
        request=request,
    )

    return _finding_to_response(updated)


@router.post(
    "/{finding_id}/confirm",
    response_model=FindingDetailResponse,
    summary="Confirm finding",
    description="Mark a finding as confirmed/verified.",
)
async def confirm_finding(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as confirmed/verified."""
    repo = FindingRepository(db)
    updated = await _update_owned_finding_status(repo, finding_id, _current_user, FindingStatus.VERIFIED)
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_status_audit_details(updated, "confirm"),
        request=request,
    )
    return _finding_to_response(updated)


@router.post(
    "/{finding_id}/dismiss",
    response_model=FindingDetailResponse,
    summary="Dismiss finding",
    description="Dismiss a finding, removing it from active consideration.",
)
async def dismiss_finding(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Dismiss a finding."""
    repo = FindingRepository(db)
    updated = await _update_owned_finding_status(repo, finding_id, _current_user, FindingStatus.DISMISSED)
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_status_audit_details(updated, "dismiss"),
        request=request,
    )
    return _finding_to_response(updated)


@router.post(
    "/{finding_id}/retest",
    response_model=FindingDetailResponse,
    summary="Request retest",
    description="Request a retest for a finding to re-validate its status.",
)
async def retest_finding(
    finding_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Request retest for a finding."""
    repo = FindingRepository(db)
    updated = await _update_owned_finding_status(repo, finding_id, _current_user, FindingStatus.RETEST_PENDING)
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(_current_user.id),
        details=_finding_status_audit_details(updated, "retest"),
        request=request,
    )
    return _finding_to_response(updated)


# --- Bulk Operations ---


class BulkUpdateRequest(BaseModel):
    """Request body for bulk-updating findings."""

    finding_ids: list[str] = Field(..., max_length=MAX_BULK_FINDINGS)
    update: FindingUpdate


class BulkUpdateResponse(BaseModel):
    """Response for bulk update."""

    updated: int


@router.post(
    "/bulk-update",
    response_model=BulkUpdateResponse,
    summary="Bulk update findings",
    description="Update multiple findings at once. Maximum 100 per request.",
)
async def bulk_update_findings(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Bulk update multiple findings. Max 100 per request."""
    if len(request.finding_ids) > MAX_BULK_FINDINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_BULK_FINDINGS} findings per batch",
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
        finding = await repo.get_by_id(fid)
        if not finding:
            continue
        check_resource_owner(finding, _current_user, "finding")
        result = await repo.update(fid, **update_data)
        if result:
            updated_count += 1
    await db.commit()

    return BulkUpdateResponse(updated=updated_count)
