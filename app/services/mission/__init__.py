"""
Mission management services.

Provides:
- Mission: Individual mission state and tracking
- MissionExecutor: Task and exploitation execution
- MissionManager: High-level orchestration
"""

from app.services.mission.executor import MissionExecutor
from app.services.mission.manager import MissionManager, mission_manager
from app.services.mission.mission import Mission
from app.services.mission.types import (
    AttackSurfaceSummary,
    MissionProgress,
    ServiceInfo,
    ToolExecutionRecord,
    VulnInfo,
)

__all__ = [
    "AttackSurfaceSummary",
    "Mission",
    "MissionExecutor",
    "MissionManager",
    "MissionProgress",
    "ServiceInfo",
    "ToolExecutionRecord",
    "VulnInfo",
    "mission_manager",
]
