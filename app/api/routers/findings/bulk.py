"""Findings bulk operations and export endpoints."""

from __future__ import annotations

import csv
import json
import logging
from io import StringIO

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.routers.findings.core import FindingUpdate
from app.auth.rate_limit import RateLimits, limiter
from spectra_common.constants import MAX_BULK_FINDINGS, MAX_EXPORT_ROWS
from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.repositories.finding import FindingRepository
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Export helpers ---

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
        return list(await repo.find_many_by(user_id=str(user.id), skip=0, limit=MAX_EXPORT_ROWS))
    return list(await repo.get_all(skip=0, limit=MAX_EXPORT_ROWS))


def _finding_to_export_dict(finding) -> dict[str, object]:
    return {
        "id": finding.id,
        "severity": finding.severity.value,
        "title": finding.title,
        "description": finding.description,
        "tool_source": finding.tool_source,
        "target_id": finding.target_id,
        "cve_id": finding.cve_id,
        "cvss_score": finding.cvss_score,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


def _require_export_password(password: str | None) -> str:
    if not password:
        raise HTTPException(
            status_code=400,
            detail="X-Export-Password header required when encrypted=true",
        )
    return password


def _build_export_response(
    payload: bytes,
    *,
    encrypted: bool,
    password: str | None,
    filename: str,
    media_type: str,
) -> FastAPIResponse:
    response_media_type = media_type
    response_filename = filename

    if encrypted:
        from app.auth.encryption import encrypt_data_with_password

        payload = encrypt_data_with_password(
            payload,
            _require_export_password(password),
        )
        response_media_type = "application/octet-stream"
        response_filename = f"{filename}.enc"

    return FastAPIResponse(
        content=payload,
        media_type=response_media_type,
        headers={"Content-Disposition": f"attachment; filename={response_filename}"},
    )


# --- Export Endpoints ---


@router.get(
    "/export/csv",
    summary="Export findings as CSV",
    description="Export all findings as a CSV file. Optionally encrypt with a password.",
)
@limiter.limit(RateLimits.FINDINGS_EXPORT)
async def export_findings_csv(
    request: Request = None,  # type: ignore[assignment]
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FastAPIResponse:
    """Export all findings as CSV."""
    findings = await _fetch_all_findings(db, _current_user)

    await audit_log_event(
        db,
        AuditEventType.DATA_EXPORTED,
        user_id=str(_current_user.id),
        details={"action": "findings_exported", "format": "csv", "count": len(findings)},
        request=request,
    )

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for finding in findings:
        export_data = _finding_to_export_dict(finding)
        writer.writerow([_sanitize_csv_value(export_data[column]) for column in _CSV_COLUMNS])

    return _build_export_response(
        buf.getvalue().encode(),
        encrypted=encrypted,
        password=password,
        filename="spectra_findings.csv",
        media_type="text/csv",
    )


@router.get(
    "/export/json",
    summary="Export findings as JSON",
    description="Export all findings as a JSON file. Optionally encrypt with a password.",
)
@limiter.limit(RateLimits.FINDINGS_EXPORT)
async def export_findings_json(
    request: Request = None,  # type: ignore[assignment]
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> FastAPIResponse:
    """Export all findings as JSON."""
    findings = await _fetch_all_findings(db, _current_user)

    await audit_log_event(
        db,
        AuditEventType.DATA_EXPORTED,
        user_id=str(_current_user.id),
        details={"action": "findings_exported", "format": "json", "count": len(findings)},
        request=request,
    )

    payload = json.dumps(
        [_finding_to_export_dict(finding) for finding in findings],
        indent=2,
    ).encode()

    return _build_export_response(
        payload,
        encrypted=encrypted,
        password=password,
        filename="spectra_findings.json",
        media_type="application/json",
    )


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
    from sqlalchemy import func, update

    from app.models.finding import Finding

    if len(request.finding_ids) > MAX_BULK_FINDINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_BULK_FINDINGS} findings per batch",
        )

    update_data = request.update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update_data["updated_at"] = func.now()

    stmt = (
        update(Finding)
        .where(Finding.id.in_(request.finding_ids))
    )
    # Non-superusers may only update their own findings
    if not _current_user.is_superuser:
        stmt = stmt.where(Finding.user_id == str(_current_user.id))

    stmt = stmt.values(**update_data)
    result = await db.execute(stmt)
    await db.commit()

    return BulkUpdateResponse(updated=result.rowcount)  # type: ignore[union-attr]
