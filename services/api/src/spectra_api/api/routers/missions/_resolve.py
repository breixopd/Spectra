"""Resolve in-memory missions or persisted checkpoint/DB fallbacks for live UI endpoints."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import check_resource_owner, validate_uuid_param
from spectra_mission.framework_progress import framework_phase_timeline
from spectra_mission.manager import mission_manager
from spectra_mission.mission import Mission
from spectra_mission.output_model import get_mission_summary_dict
from spectra_mission.task_tree import PentestTaskTree
from spectra_mission.types import MissionProgress
from spectra_persistence.models.user import User
from spectra_persistence.repositories.mission import MissionRepository

logger = logging.getLogger(__name__)


async def _load_db_mission(mission_id: str, session: AsyncSession, user: User):
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(session)
    db_mission = await repo.get_by_id(mission_id)
    if not db_mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(db_mission, user, "mission")
    return db_mission


async def resolve_runtime_mission(
    mission_id: str,
    session: AsyncSession,
    user: User,
) -> Mission | None:
    """Return an in-memory or checkpoint-hydrated mission, or None if only DB row exists."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, user, "mission")
        return active

    db_mission = await _load_db_mission(mission_id, session, user)
    checkpoint = db_mission.checkpoint_data
    if isinstance(checkpoint, dict) and checkpoint:
        try:
            return Mission.from_checkpoint(checkpoint)
        except ValueError:
            logger.warning("Mission %s has an invalid durable checkpoint", mission_id)
    return None


def progress_from_persisted(db_mission) -> MissionProgress:
    """Framework-phase progress when the mission is not loaded in memory."""
    summary = get_mission_summary_dict(db_mission)
    current_phase = summary.get("current_phase")
    fw = summary.get("pentest_framework")
    timeline = framework_phase_timeline(
        current_phase=current_phase,
        mission_status=db_mission.status,
        pentest_framework=fw,
    )
    total = len(timeline) or 1
    done = sum(1 for phase in timeline if phase.get("done"))
    percent = round(done / total * 100, 1)
    return MissionProgress(
        percent=percent,
        phase=str(current_phase or "unknown"),
        completed_tasks=done,
        total_tasks=total,
        active_tasks=[],
    )


def empty_task_tree_payload(mission_id: str) -> dict:
    tree = PentestTaskTree(mission_id)
    return {**tree.to_dict(), "tasks": []}


def task_tree_payload_from_mission(mission: Mission) -> dict:
    tree = mission.task_tree.to_dict()
    tree["tasks"] = mission.task_tree_ui_tasks()
    return tree


async def resolve_mission_progress(
    mission_id: str,
    session: AsyncSession,
    user: User,
) -> MissionProgress:
    mission = await resolve_runtime_mission(mission_id, session, user)
    if mission:
        return mission.get_progress()
    db_mission = await _load_db_mission(mission_id, session, user)
    return progress_from_persisted(db_mission)


async def resolve_mission_task_tree(
    mission_id: str,
    session: AsyncSession,
    user: User,
) -> dict:
    mission = await resolve_runtime_mission(mission_id, session, user)
    if mission:
        return task_tree_payload_from_mission(mission)
    await _load_db_mission(mission_id, session, user)
    return empty_task_tree_payload(mission_id)
