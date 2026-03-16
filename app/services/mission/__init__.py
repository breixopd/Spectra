"""Mission management services package."""

from app.services.mission.types import AttackSurfaceSummary, MissionProgress, ServiceInfo, ToolExecutionRecord, VulnInfo

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


def __getattr__(name: str):
    """Resolve heavy mission exports lazily to avoid package import cycles."""
    if name == "MissionExecutor":
        from app.services.mission.executor import MissionExecutor

        return MissionExecutor
    if name in {"MissionManager", "mission_manager"}:
        from app.services.mission.manager import MissionManager, mission_manager

        return {"MissionManager": MissionManager, "mission_manager": mission_manager}[name]
    if name == "Mission":
        from app.services.mission.mission import Mission

        return Mission
    raise AttributeError(name)
