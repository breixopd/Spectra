"""Mission catalog routes — presets, summary, playbooks, chains, attack summary (no /{mission_id} paths)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.services.mission.output_model import get_mission_finding_counts

router = APIRouter()


class CreateChainRequest(BaseModel):
    """Schema for creating a custom exploit chain."""

    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=1000)
    stages: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/presets", response_model=None)
async def get_scan_presets(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, dict[str, Any]]:
    """Get available scan presets."""
    from app.services.mission.presets import SCAN_PRESETS

    return SCAN_PRESETS


@router.get("/summary", tags=["Missions"])
async def get_missions_summary(
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Get aggregated mission summary with finding counts — paginated."""
    from sqlalchemy import func, select

    from app.models.mission import Mission

    base = select(Mission)
    if not _current_user.is_superuser:
        base = base.where(Mission.user_id == str(_current_user.id))

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    # Paginated results
    stmt = base.order_by(Mission.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    db_missions = result.scalars().all()

    missions: list[dict[str, Any]] = [
        {
            "id": str(m.id),
            "target": m.target,
            "directive": m.directive,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "findings": get_mission_finding_counts(m),
        }
        for m in db_missions
    ]

    totals: dict[str, int] = {
        "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "total": 0
    }
    for sev in ("critical", "high", "medium", "low", "info"):
        totals[sev] = sum(m["findings"][sev] for m in missions)
    totals["total"] = sum(m["findings"]["total"] for m in missions)

    return {"missions": missions, "totals": totals, "count": len(missions), "total": total, "skip": skip, "limit": limit}


@router.get("/adversary-playbooks")
async def get_adversary_playbooks(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available adversary simulation playbooks."""
    from app.services.ai.adversary_playbooks import list_adversary_playbooks

    return list_adversary_playbooks()


@router.get("/adversary-playbooks/{playbook_id}")
async def get_adversary_playbook_detail(
    playbook_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get full details of an adversary playbook."""
    from app.services.ai.adversary_playbooks import get_adversary_playbook

    pb = get_adversary_playbook(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb.model_dump()


@router.get("/exploit-chains")
async def get_exploit_chains(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available exploit chains (builtin + custom)."""
    from app.services.mission.chain_builder import get_builtin_chains, load_custom_chains

    builtin = [c.model_dump() for c in get_builtin_chains()]
    custom = [c.model_dump() for c in load_custom_chains()]
    return builtin + custom


@router.post("/exploit-chains")
async def create_exploit_chain(
    chain_in: CreateChainRequest,
    _current_user: User = require_permission(Permission.MANAGE_TOOLS),
) -> dict[str, Any]:
    """Create a custom exploit chain."""
    from app.services.mission.chain_builder import ChainBuilder, save_custom_chain

    chain = ChainBuilder.create_chain(chain_in.name, chain_in.stages)
    chain.description = chain_in.description

    warnings = ChainBuilder.validate_chain(chain)
    save_custom_chain(chain)

    return {"chain": chain.model_dump(), "warnings": warnings}


@router.get("/attack-summary")
async def get_attack_coverage(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get MITRE ATT&CK technique coverage from all recent missions."""
    from app.services.ai.mitre_attack import get_attack_summary

    # Get recent mission findings from memory
    try:
        from app.services.ai.memory import get_memory

        memory = get_memory(str(_current_user.id))
        findings: list[dict[str, str]] = []
        for lesson in memory.tool_lessons[-50:]:
            findings.append({"tool_name": lesson.tool_id, "source": "tool_execution"})
        return get_attack_summary(findings)
    except (OSError, RuntimeError, ValueError):
        return {"tactics": {}, "total_techniques": 0}
