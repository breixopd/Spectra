"""Findings core endpoints — CRUD, list, status actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.requests import Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_api.api.dependencies import check_resource_owner, get_current_active_user, validate_uuid_param
from spectra_api.api.schemas.common import PaginatedResponse
from spectra_api.api.schemas.finding import FindingDetailResponse, finding_to_response
from spectra_api.authz import Permission, require_permission
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_common.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from spectra_common.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from spectra_persistence.database import get_async_session
from spectra_persistence.finding_evidence import (
    has_reproducible_evidence,
    initial_proof_status,
    prepare_evidence_storage,
    proof_status_for_status_change,
)
from spectra_persistence.models.audit_log import AuditEventType
from spectra_persistence.models.finding import Finding, FindingStatus, ProofStatus, Severity
from spectra_persistence.models.user import User
from spectra_persistence.repositories.finding import FindingRepository
from spectra_persistence.repositories.target import TargetRepository
from spectra_system.audit import log_event as audit_log_event

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
    proof_status: ProofStatus | None = Field(None, description="Optional explicit proof status override")
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)
    tool_source: str = Field(..., max_length=100)
    evidence: dict[str, Any] | None = None

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > 25:
            raise ValueError("Evidence may contain at most 25 entries")
        for key, item in value.items():
            if len(key) > 100:
                raise ValueError("Evidence keys must be 100 characters or fewer")
            if isinstance(item, str) and len(item) > 5000:
                raise ValueError("Evidence values must be 5000 characters or fewer")
        return value

    @model_validator(mode="after")
    def require_artifact_for_high_severity(self) -> FindingCreate:
        if self.severity in {Severity.HIGH, Severity.CRITICAL} and not has_reproducible_evidence(self.evidence):
            raise ValueError(
                "High and critical findings require artifact_id, tool_execution_id, s3_key, or sha256 evidence"
            )
        return self


class FindingUpdate(BaseModel):
    """Schema for updating a finding."""

    title: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=50000)
    severity: Severity | None = None
    status: FindingStatus | None = None
    proof_status: ProofStatus | None = None
    cvss_score: float | None = Field(None, ge=0.0, le=10.0)
    cve_id: str | None = Field(None, max_length=20)


def _finding_filters(
    current_user: User,
    *,
    severity: Severity | None = None,
    status_filter: FindingStatus | None = None,
    proof_status_filter: ProofStatus | None = None,
) -> dict[str, object]:
    filters: dict[str, object] = {}
    if not current_user.is_superuser:
        filters["user_id"] = str(current_user.id)
    if severity is not None:
        filters["severity"] = severity
    if status_filter is not None:
        filters["status"] = status_filter
    if proof_status_filter is not None:
        filters["proof_status"] = proof_status_filter
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
        "proof_status": finding.proof_status.value,
        "action": action,
    }


def _proof_fields_for_create(
    status: FindingStatus,
    evidence: dict[str, Any] | None,
    explicit_proof_status: ProofStatus | None,
) -> tuple[ProofStatus, datetime | None]:
    proof_status = explicit_proof_status or initial_proof_status(status, evidence)
    verified_at = datetime.now(UTC) if proof_status == ProofStatus.VERIFIED else None
    return proof_status, verified_at


def _proof_fields_for_status_change(
    new_status: FindingStatus,
    *,
    current_proof_status: ProofStatus,
) -> tuple[ProofStatus, datetime | None]:
    proof_status = proof_status_for_status_change(new_status, current=current_proof_status)
    verified_at = datetime.now(UTC) if proof_status == ProofStatus.VERIFIED else None
    return proof_status, verified_at


async def _get_finding_or_404(repo: FindingRepository, finding_id: str):
    validate_uuid_param(finding_id, "finding_id")
    finding = await repo.get_by_id(finding_id, options=[selectinload(Finding.target)])
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
    existing = await _get_owned_finding_or_404(repo, finding_id, current_user)
    proof_status, verified_at = _proof_fields_for_status_change(
        new_status,
        current_proof_status=existing.proof_status,
    )
    return await repo.update(
        finding_id,
        status=new_status,
        proof_status=proof_status,
        verified_at=verified_at,
    )


async def _update_finding_status_response(
    repo: FindingRepository,
    db: AsyncSession,
    finding_id: str,
    current_user: User,
    new_status: FindingStatus,
    action: str,
    request: Request,
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
    reloaded = await repo.get_by_id(finding_id, options=[selectinload(Finding.target)])
    if reloaded is None:
        raise HTTPException(status_code=500, detail="Updated finding could not be reloaded")
    return finding_to_response(reloaded)


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
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> FindingDetailResponse:
    """Create a new finding."""
    validate_uuid_param(finding_in.target_id, "target_id")
    target_repo = TargetRepository(db)
    target = await target_repo.get_by_id(finding_in.target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target not found",
        )
    check_resource_owner(target, _current_user, "target")

    repo = FindingRepository(db)
    stored_evidence = prepare_evidence_storage(finding_in.evidence)
    proof_status, verified_at = _proof_fields_for_create(
        finding_in.status,
        stored_evidence,
        finding_in.proof_status,
    )

    finding = await repo.create(
        target_id=finding_in.target_id,
        title=finding_in.title,
        description=finding_in.description,
        severity=finding_in.severity,
        status=finding_in.status,
        proof_status=proof_status,
        verified_at=verified_at,
        cvss_score=finding_in.cvss_score,
        cve_id=finding_in.cve_id,
        tool_source=finding_in.tool_source,
        evidence=stored_evidence,
        user_id=str(_current_user.id),
    )
    finding.target = target
    await db.commit()
    await audit_log_event(
        db,
        AuditEventType.FINDING_CREATED,
        user_id=str(_current_user.id),
        details={
            "finding_id": finding.id,
            "target_id": finding.target_id,
            "severity": finding.severity.value,
            "proof_status": finding.proof_status.value,
            "title": finding.title,
        },
        request=request,
    )

    return finding_to_response(finding)


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List findings",
    description="Retrieve all findings with optional severity and status filters.",
)
@limiter.limit(RateLimits.FINDINGS_LIST)
async def list_findings(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    severity: Severity | None = None,
    status_filter: FindingStatus | None = Query(None, alias="status"),
    proof_status_filter: ProofStatus | None = Query(None, alias="proof_status"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> PaginatedResponse:
    """List all findings with optional filters.

    Pagination: max 100 items per page.
    """
    repo = FindingRepository(db)
    filters = _finding_filters(
        _current_user,
        severity=severity,
        status_filter=status_filter,
        proof_status_filter=proof_status_filter,
    )

    total = await repo.count(**filters)
    skip = (page - 1) * per_page

    options = [selectinload(Finding.target)]
    if filters:
        findings = await repo.find_many_by(skip=skip, limit=per_page, options=options, **filters)
    else:
        findings = await repo.get_all(skip=skip, limit=per_page, options=options)

    items = [finding_to_response(finding) for finding in findings]
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
    return finding_to_response(finding)


@router.patch(
    "/{finding_id}",
    response_model=FindingDetailResponse,
    summary="Update finding",
    description="Partially update a finding's fields such as title, severity, or status.",
)
async def update_finding(
    finding_id: str,
    finding_in: FindingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_FINDINGS),
) -> FindingDetailResponse:
    """Update a finding."""
    repo = FindingRepository(db)
    existing = await _get_owned_finding_or_404(repo, finding_id, _current_user)

    update_data = finding_in.model_dump(exclude_unset=True)
    requested_severity = update_data.get("severity")
    if requested_severity in {Severity.HIGH, Severity.CRITICAL} and not has_reproducible_evidence(existing.evidence):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="High and critical findings require artifact_id, tool_execution_id, s3_key, or sha256 evidence",
        )

    new_status = update_data.get("status")
    if new_status is not None and "proof_status" not in update_data:
        proof_status, verified_at = _proof_fields_for_status_change(
            new_status,
            current_proof_status=existing.proof_status,
        )
        update_data["proof_status"] = proof_status
        update_data["verified_at"] = verified_at
    elif update_data.get("proof_status") == ProofStatus.VERIFIED and "verified_at" not in update_data:
        update_data["verified_at"] = datetime.now(UTC)

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

    updated = await _get_owned_finding_or_404(repo, finding_id, _current_user)
    return finding_to_response(updated)


@router.delete(
    "/{finding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete finding",
    description="Permanently delete a security finding.",
)
async def delete_finding(
    finding_id: str,
    request: Request,
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
    request: Request,
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
    request: Request,
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
    request: Request,
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
    request: Request,
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
    request: Request,
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
