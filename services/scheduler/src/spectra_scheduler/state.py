"""Process-local singleton for linking FastAPI lifespan to SchedulerService."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spectra_scheduler.service import SchedulerService

_scheduler_instance: SchedulerService | None = None
