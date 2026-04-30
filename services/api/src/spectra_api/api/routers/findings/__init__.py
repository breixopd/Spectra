"""Findings API Router — re-exports combined router from sub-modules."""

from fastapi import APIRouter

from spectra_api.api.routers.findings.bulk import router as bulk_router
from spectra_api.api.routers.findings.core import router as core_router

router = APIRouter(tags=["Findings"])

# Merge sub-router routes directly (same rationale as missions/__init__.py).
# Bulk/export routes first to avoid path conflicts with /{finding_id}.
for _sub in (bulk_router, core_router):
    router.routes.extend(_sub.routes)
