"""Findings core endpoints — CRUD, list, status actions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import check_resource_owner, get_current_active_user, validate_uuid_param
from app.api.schemas import FindingResponse, PaginatedResponse
from app.core.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from app.core.database import get_async_session
from app.core.rate_limit import RateLimits, limiter
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.finding import FindingStatus, Severity
from app.models.user import User
from app.repositories.finding import FindingRepository
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Schemas ---


class FindingCreate(BaseModel):
    """Schema for creating a new finding."""

    target_id: str = Field(..., description="ID of the target")
    title: str = Field(..., max_length=500)
    description: str | None = Field(None, max_length=50000)
    severity: Severity = Severity.INFO
    status: FindingStatus = FindingStatus.POTENTIAL
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)
    tool_source: str = Field(..., max_length=100)
    evidence: dict[str, str] | None = None

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if len(value) > 25:
            raise ValueError("Evidence may contain at most 25 entries")
        for key, item in value.items():
            if len(key) > 100:
                raise ValueError("Evidence keys must be 100 characters or fewer")
            if len(item) > 5000:
                raise ValueError("Evidence values must be 5000 characters or fewer")
        return value

    @model_validator(mode="after")
    def require_artifact_for_high_severity(self) -> FindingCreate:
        if self.severity in {Severity.HIGH, Severity.CRITICAL} and not _has_reproducible_evidence(self.evidence):
            raise ValueError("High and critical findings require artifact_id, tool_execution_id, s3_key, or sha256 evidence")
        return self


class FindingUpdate(BaseModel):
    """Schema for updating a finding."""

    title: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=50000)
    severity: Severity | None = None
    status: FindingStatus | None = None
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)


class FindingDetailResponse(FindingResponse):
    """Detailed finding response with all fields."""

    target_id: str
    cvss_score: float | None = None
    cve_id: str | None = None
    evidence: dict[str, str] | None = None


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


def _has_reproducible_evidence(evidence: dict[str, str] | None) -> bool:
    if not evidence:
        return False
    required = {"artifact_id", "tool_execution_id", "s3_key", "sha256"}
    return any(bool(evidence.get(key)) for key in required)


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
    validate_uuid_param(finding_id, "finding_id")
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


async def _update_finding_status_response(
    repo: FindingRepository,
    db: AsyncSession,
    finding_id: str,
    current_user: User,
    new_status: FindingStatus,
    action: str,
    request: Request | None,
    *,
    ensure_updated: bool = False,
) -> FindingDetailResponse:
    updated = await _update_owned_finding_status(
        repo,
        finding_id,
        current_user,
        new_status,
    )
    await db.commit()
    if ensure_updated and not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update failed unexpectedly",
        )
    await audit_log_event(
        db,
        AuditEventType.FINDING_UPDATED,
        user_id=str(current_user.id),
        details=_finding_status_audit_details(updated, action),
        request=request,
    )
    return _finding_to_response(updated)


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
    request: Request = None,  # type: ignore[assignment]
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
    request: Request = None,  # type: ignore[assignment]
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
    from app.models.finding import Finding

    repo = FindingRepository(db)
    filters = _finding_filters(_current_user, severity=severity, status_filter=status_filter)

    total = await repo.count(**filters)
    skip = (page - 1) * per_page

    options = [selectinload(Finding.target)]
    if filters:
        findings = await repo.find_many_by(skip=skip, limit=per_page, options=options, **filters)
    else:
        findings = await repo.get_all(skip=skip, limit=per_page, options=options)

    items = [_finding_to_response(finding) for finding in findings]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


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
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> FindingDetailResponse:
    """Update a finding."""
    repo = FindingRepository(db)
    existing = await _get_owned_finding_or_404(repo, finding_id, _current_user)

    # Filter out None values
    update_data = finding_in.model_dump(exclude_unset=True)
    requested_severity = update_data.get("severity")
    if requested_severity in {Severity.HIGH, Severity.CRITICAL} and not _has_reproducible_evidence(existing.evidence):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="High and critical findings require artifact_id, tool_execution_id, s3_key, or sha256 evidence",
        )

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
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> None:
    """Delete a finding."""
    repo = FindingRepository(db)
    existing = await _get_owned_finding_or_404(repo, finding_id, _current_user)

    details = {
        "finding_id": existing.id,
        "target_id": existing.target_id,
        "title": existing.title,
        "severity": existing.severity.value,
    }
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
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as verified."""
    repo = FindingRepository(db)
    return await _update_finding_status_response(
        repo,
        db,
        finding_id,
        _current_user,
        FindingStatus.VERIFIED,
        "verify",
        request,
        ensure_updated=True,
    )


@router.post(
    "/{finding_id}/false-positive",
    response_model=FindingDetailResponse,
    summary="Mark false positive",
    description="Mark a finding as a false positive to exclude it from active results.",
)
async def mark_false_positive(
    finding_id: str,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as a false positive."""
    repo = FindingRepository(db)
    return await _update_finding_status_response(
        repo,
        db,
        finding_id,
        _current_user,
        FindingStatus.FALSE_POSITIVE,
        "mark_false_positive",
        request,
        ensure_updated=True,
    )


@router.post(
    "/{finding_id}/confirm",
    response_model=FindingDetailResponse,
    summary="Confirm finding",
    description="Mark a finding as confirmed/verified.",
)
async def confirm_finding(
    finding_id: str,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FindingDetailResponse:
    """Mark a finding as confirmed/verified."""
    repo = FindingRepository(db)
    return await _update_finding_status_response(
        repo,
        db,
        finding_id,
        _current_user,
        FindingStatus.VERIFIED,
        "confirm",
        request,
    )


@router.post(
    "/{finding_id}/dismiss",
    response_model=FindingDetailResponse,
    summary="Dismiss finding",
    description="Dismiss a finding, removing it from active consideration.",
)
async def dismiss_finding(
    finding_id: str,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Dismiss a finding."""
    repo = FindingRepository(db)
    return await _update_finding_status_response(
        repo,
        db,
        finding_id,
        _current_user,
        FindingStatus.DISMISSED,
        "dismiss",
        request,
    )


@router.post(
    "/{finding_id}/retest",
    response_model=FindingDetailResponse,
    summary="Request retest",
    description="Request a retest for a finding to re-validate its status.",
)
async def retest_finding(
    finding_id: str,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Request retest for a finding."""
    repo = FindingRepository(db)
    return await _update_finding_status_response(
        repo,
        db,
        finding_id,
        _current_user,
        FindingStatus.RETEST_PENDING,
        "retest",
        request,
    )
