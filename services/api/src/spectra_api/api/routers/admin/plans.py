"""Admin plan management endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.schemas.system import PlanCreate, PlanResponse, PlanUpdate
from spectra_api.authz import Permission, require_permission
from spectra_platform.core.database import get_async_session
from spectra_platform.models.audit_log import AuditEventType
from spectra_platform.models.plan import Plan
from spectra_platform.models.user import User
from spectra_platform.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/admin/plans")
async def list_plans(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> list[PlanResponse]:
    rows = (await session.execute(select(Plan).order_by(Plan.sort_order, Plan.name))).scalars().all()
    return [
        PlanResponse(
            id=p.id,
            name=p.name,
            display_name=p.display_name,
            description=p.description,
            is_active=p.is_active,
            is_default=p.is_default,
            allow_self_service_registration=p.allow_self_service_registration,
            sort_order=p.sort_order,
            max_concurrent_missions=p.max_concurrent_missions,
            max_missions_per_month=p.max_missions_per_month,
            max_missions_per_day=p.max_missions_per_day,
            max_missions_per_week=p.max_missions_per_week,
            max_targets=p.max_targets,
            max_api_requests_per_hour=p.max_api_requests_per_hour,
            max_api_requests_per_day=p.max_api_requests_per_day,
            sandbox_max_containers=p.sandbox_max_containers,
            max_storage_mb=p.max_storage_mb,
            sandbox_resource_tier=p.sandbox_resource_tier,
            features=p.features,
        )
        for p in rows
    ]


@router.post("/api/admin/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreate,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> PlanResponse:
    dup = (await session.execute(select(Plan.id).where(Plan.name == body.name))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="Plan name already exists")

    plan = Plan(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        is_active=True,
        is_default=body.is_default,
        allow_self_service_registration=body.allow_self_service_registration,
        sort_order=body.sort_order,
        max_concurrent_missions=body.max_concurrent_missions,
        max_missions_per_month=body.max_missions_per_month,
        max_missions_per_day=body.max_missions_per_day,
        max_missions_per_week=body.max_missions_per_week,
        max_targets=body.max_targets,
        max_api_requests_per_hour=body.max_api_requests_per_hour,
        max_api_requests_per_day=body.max_api_requests_per_day,
        sandbox_max_containers=body.sandbox_max_containers,
        max_storage_mb=body.max_storage_mb,
        sandbox_resource_tier=body.sandbox_resource_tier,
        features=body.features,
    )
    session.add(plan)
    await session.flush()
    await session.refresh(plan)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_created", "plan": plan.name},
        request=request,
    )
    await session.commit()

    return PlanResponse(
        id=plan.id,
        name=plan.name,
        display_name=plan.display_name,
        description=plan.description,
        is_active=plan.is_active,
        is_default=plan.is_default,
        allow_self_service_registration=plan.allow_self_service_registration,
        sort_order=plan.sort_order,
        max_concurrent_missions=plan.max_concurrent_missions,
        max_missions_per_month=plan.max_missions_per_month,
        max_missions_per_day=plan.max_missions_per_day,
        max_missions_per_week=plan.max_missions_per_week,
        max_targets=plan.max_targets,
        max_api_requests_per_hour=plan.max_api_requests_per_hour,
        max_api_requests_per_day=plan.max_api_requests_per_day,
        sandbox_max_containers=plan.sandbox_max_containers,
        max_storage_mb=plan.max_storage_mb,
        sandbox_resource_tier=plan.sandbox_resource_tier,
        features=plan.features,
    )


@router.put("/api/admin/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: PlanUpdate,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> PlanResponse:
    plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    for field in (
        "display_name",
        "description",
        "is_active",
        "is_default",
        "allow_self_service_registration",
        "sort_order",
        "max_concurrent_missions",
        "max_missions_per_month",
        "max_missions_per_day",
        "max_missions_per_week",
        "max_targets",
        "max_api_requests_per_hour",
        "max_api_requests_per_day",
        "sandbox_max_containers",
        "max_storage_mb",
        "sandbox_resource_tier",
        "features",
    ):
        val = getattr(body, field, None)
        if val is not None:
            setattr(plan, field, val)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_updated", "plan": plan.name},
        request=request,
    )
    await session.commit()
    await session.refresh(plan)

    return PlanResponse(
        id=plan.id,
        name=plan.name,
        display_name=plan.display_name,
        description=plan.description,
        is_active=plan.is_active,
        is_default=plan.is_default,
        allow_self_service_registration=plan.allow_self_service_registration,
        sort_order=plan.sort_order,
        max_concurrent_missions=plan.max_concurrent_missions,
        max_missions_per_month=plan.max_missions_per_month,
        max_missions_per_day=plan.max_missions_per_day,
        max_missions_per_week=plan.max_missions_per_week,
        max_targets=plan.max_targets,
        max_api_requests_per_hour=plan.max_api_requests_per_hour,
        max_api_requests_per_day=plan.max_api_requests_per_day,
        sandbox_max_containers=plan.sandbox_max_containers,
        max_storage_mb=plan.max_storage_mb,
        sandbox_resource_tier=plan.sandbox_resource_tier,
        features=plan.features,
    )


@router.delete("/api/admin/plans/{plan_id}")
async def deactivate_plan(
    plan_id: str,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.is_active = False
    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_deactivated", "plan": plan.name},
        request=request,
    )
    await session.commit()
    return {"detail": "Plan deactivated"}
