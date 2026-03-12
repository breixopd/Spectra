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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.database import get_async_session
from app.core.rate_limit import limiter
from app.models.exploit import Exploit
from app.models.finding import Finding
from app.models.mission import Mission
from app.models.target import Target
from app.models.user import User

logger = logging.getLogger("spectra.api.export")

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
_MAX_EXPORT_ROWS = 10_000


def _sanitize_csv_value(val: object) -> str:
    s = str(val) if val is not None else ""
    if s and s[0] in _CSV_INJECTION_CHARS:
        return "'" + s
    return s


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in columns:
        val = getattr(row, col, None)
        if isinstance(val, dt):
            val = val.isoformat()
        elif hasattr(val, "value"):  # enum
            val = val.value  # type: ignore[union-attr]
        result[col] = val
    return result


@router.get(
    "/{entity_type}",
    summary="Export data",
    description="Export entity data as JSON or CSV. Supports date range and status filters.",
)
@limiter.limit("10/minute")
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
    stmt = select(model)

    # User isolation
    if not _current_user.is_superuser and hasattr(model, "user_id"):
        stmt = stmt.where(model.user_id == str(_current_user.id))

    # Status filter
    if status and hasattr(model, "status"):
        stmt = stmt.where(model.status == status)

    # Date range filter
    date_col = model.timestamp if entity_type == "exploits" else model.created_at  # type: ignore[attr-defined]
    if date_from:
        try:
            from_dt = dt.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_from: {date_from}")
        stmt = stmt.where(date_col >= from_dt)
    if date_to:
        try:
            to_dt = dt.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_to: {date_to}")
        stmt = stmt.where(date_col <= to_dt)

    stmt = stmt.limit(_MAX_EXPORT_ROWS)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if format == "csv":
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in rows:
            d = _row_to_dict(row, columns)
            writer.writerow([_sanitize_csv_value(d[c]) for c in columns])

        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=spectra_{entity_type}.csv"},
        )

    # JSON (default)
    data = [_row_to_dict(row, columns) for row in rows]
    content = json.dumps(data, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=spectra_{entity_type}.json"},
    )
