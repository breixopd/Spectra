"""Mission API Router — re-exports combined router from sub-modules."""

from fastapi import APIRouter

router = APIRouter(tags=["Missions"])

# Import sub-module routers (each uses APIRouter() with no prefix).
from app.api.routers.missions.artifacts import router as _artifacts
from app.api.routers.missions.core import router as _core
from app.api.routers.missions.export import router as _export
from app.api.routers.missions.feedback import router as _feedback

# Merge sub-router routes directly into the parent router.
# We cannot use include_router() because FastAPI >= 0.100 rejects
# include_router(prefix="") when any route has path="", *and* rejects
# prefix="/" (must not end with "/").  Appending routes directly
# preserves the original monolithic-file semantics exactly.
for _sub in (_core, _export, _feedback, _artifacts):
    router.routes.extend(_sub.routes)

# Re-export schemas used by tests for backward compatibility
from app.api.routers.missions.core import CreateChainRequest
from app.api.routers.missions.feedback import SteerMissionRequest
