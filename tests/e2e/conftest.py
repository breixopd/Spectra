import asyncio
from typing import List

from app.services.mission.manager import MissionManager


async def wait_for_mission_status(
    mission_manager: MissionManager,
    mission_id: str,
    target_statuses: List[str],
    timeout: float = 10.0,
    interval: float = 0.5,
) -> str:
    """Wait for mission to reach one of the target statuses."""
    start_time = asyncio.get_running_loop().time()
    while (asyncio.get_running_loop().time() - start_time) < timeout:
        mission = await mission_manager.get_mission(mission_id)
        if mission and mission.status in target_statuses:
            return mission.status
        await asyncio.sleep(interval)

    mission = await mission_manager.get_mission(mission_id)
    current_status = mission.status if mission else "unknown"
    raise TimeoutError(
        f"Mission {mission_id} did not reach {target_statuses} in {timeout}s. Current: {current_status}"
    )


async def get_mission_logs(
    mission_manager: MissionManager, mission_id: str
) -> List[str]:
    """Get logs for a mission."""
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        return []
    return mission.logs
