"""
Data Export API Router.

Provides bulk data export in JSON and CSV formats for SaaS consumers.
Supports: missions, findings, targets, exploits.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime as dt
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from spectra_common.constants import MAX_EXPORT_ROWS
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.auth.rate_limit import RateLimits, limiter
from app.core.database import get_async_session
from app.models.exploit import Exploit
from app.models.finding import Finding, FindingStatus
from app.models.mission import Mission, MissionStatus
from app.models.target import Target, TargetStatus
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["Export"])

_ENTITY_MODELS: dict[str, type] = {
    "missions": Mission,
    "findings": Finding,
    "targets": Target,
    "exploits": Exploit,
}

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")

# Column definitions per entity type
_COLUMNS: dict[str, list[str]] = {
    "missions": ["id", "target", "directive", "status", "created_at"],
    "findings": [
        "id",
        "target_id",
        "title",
        "description",
        "severity",
        "status",
        "cvss_score",
        "cve_id",
        "tool_source",
        "created_at",
    ],
    "targets": ["id", "address", "description", "status", "os", "created_at"],
    "exploits": ["id", "target_id", "name", "type", "success", "output", "timestamp"],
}

_VALID_ENTITIES = frozenset(_ENTITY_MODELS.keys())
_VALID_FORMATS = frozenset({"json", "csv"})

_VALID_STATUS_FILTERS: dict[str, set[str]] = {
    "missions": {status.value for status in MissionStatus},
    "findings": {status.value for status in FindingStatus},
    "targets": {status.value for status in TargetStatus},
}


def _parse_iso_datetime(value: str, field_name: str) -> dt:
    try:
        return dt.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}: {value}") from exc


def _sanitize_csv_value(val: object) -> str:
    s = str(val) if val is not None else ""
    if s and s[0] in _CSV_INJECTION_CHARS:
        return "'" + s
    return s


def _serialize_row_value(value: Any) -> Any:
    if isinstance(value, dt):
        return value.isoformat()
    if hasattr(value, "value"):  # enum
        return value.value  # type: ignore[union-attr]
    return value


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    return {col: _serialize_row_value(getattr(row, col, None)) for col in columns}


def _build_export_query(
    entity_type: str,
    model: type,
    *,
    status: str | None,
    date_from: str | None,
    date_to: str | None,
    current_user: User,
):
    stmt = select(model)

    if not current_user.is_superuser and hasattr(model, "user_id"):
        stmt = stmt.where(model.user_id == str(current_user.id))

    if status:
        allowed_statuses = _VALID_STATUS_FILTERS.get(entity_type)
        if allowed_statuses is not None and status not in allowed_statuses:
            raise HTTPException(status_code=422, detail=f"Invalid status for {entity_type}: {status}")
        if hasattr(model, "status"):
            stmt = stmt.where(model.status == status)

    date_col = model.timestamp if entity_type == "exploits" else model.created_at  # type: ignore[attr-defined]
    if date_from:
        stmt = stmt.where(date_col >= _parse_iso_datetime(date_from, "date_from"))
    if date_to:
        stmt = stmt.where(date_col <= _parse_iso_datetime(date_to, "date_to"))

    return stmt.limit(MAX_EXPORT_ROWS)


def _render_csv_content(rows: list[Any], columns: list[str]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        row_data = _row_to_dict(row, columns)
        writer.writerow([_sanitize_csv_value(row_data[column]) for column in columns])
    return buffer.getvalue()


def _render_json_content(rows: list[Any], columns: list[str]) -> str:
    return json.dumps([_row_to_dict(row, columns) for row in rows], default=str)


def _build_export_response(entity_type: str, format: str, content: str) -> StreamingResponse:
    media_type = "text/csv" if format == "csv" else "application/json"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=spectra_{entity_type}.{format}"},
    )


@router.get(
    "/{entity_type}",
    summary="Export data",
    description="Export entity data as JSON or CSV. Supports date range and status filters.",
)
@limiter.limit(RateLimits.EXPORT_DATA)
async def export_data(
    request: Request,
    entity_type: str,
    format: str = Query(default="json", description="Output format: json or csv"),
    status: str | None = Query(default=None, description="Filter by status"),
    date_from: str | None = Query(default=None, description="ISO date lower bound (created_at / timestamp)"),
    date_to: str | None = Query(default=None, description="ISO date upper bound"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    if entity_type not in _VALID_ENTITIES:
        raise HTTPException(
            status_code=400, detail=f"Invalid entity_type. Must be one of: {', '.join(sorted(_VALID_ENTITIES))}"
        )
    if format not in _VALID_FORMATS:
        raise HTTPException(status_code=400, detail="Invalid format. Must be 'json' or 'csv'.")

    model = _ENTITY_MODELS[entity_type]
    columns = _COLUMNS[entity_type]
    stmt = _build_export_query(
        entity_type,
        model,
        status=status,
        date_from=date_from,
        date_to=date_to,
        current_user=_current_user,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if format == "csv":
        return _build_export_response(entity_type, format, _render_csv_content(rows, columns))

    return _build_export_response(entity_type, format, _render_json_content(rows, columns))
