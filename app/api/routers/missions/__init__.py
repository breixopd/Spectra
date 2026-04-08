"""Mission API Router — re-exports combined router from sub-modules."""

from fastapi import APIRouter

router = APIRouter(tags=["Missions"])

# Import sub-module routers (each uses APIRouter() with no prefix).
from app.api.routers.missions.core import router as _core  # noqa: E402
from app.api.routers.missions.export import router as _export  # noqa: E402
from app.api.routers.missions.feedback import router as _feedback  # noqa: E402

# Merge sub-router routes directly into the parent router.
# We cannot use include_router() because FastAPI >= 0.100 rejects
# include_router(prefix="") when any route has path="", *and* rejects
# prefix="/" (must not end with "/").  Appending routes directly
# preserves the original monolithic-file semantics exactly.
for _sub in (_core, _export, _feedback):
    router.routes.extend(_sub.routes)

# Re-export schemas used by tests for backward compatibility
from app.api.routers.missions.core import CreateChainRequest  # noqa: E402, F401
from app.api.routers.missions.feedback import SteerMissionRequest  # noqa: E402, F401
