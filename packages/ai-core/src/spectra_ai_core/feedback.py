"""TensorZero feedback integration for AI optimization."""

import logging

from spectra_ai_core.router import get_smart_router

logger = logging.getLogger(__name__)


async def send_task_feedback(
    inference_id: str,
    success: bool,
    metric: str = "task_success",
) -> None:
    """Send boolean feedback for a completed AI task."""
    if not inference_id:
        return
    router = get_smart_router()
    if hasattr(router, "send_feedback"):
        await router.send_feedback(inference_id, metric, success)


async def send_exploit_feedback(
    inference_id: str,
    success: bool,
) -> None:
    """Send feedback for exploit crafting results."""
    await send_task_feedback(inference_id, success, "exploit_success")


async def send_quality_score(
    inference_id: str,
    score: float,
) -> None:
    """Send a float quality score (0.0-1.0) for response quality."""
    if not inference_id or not (0.0 <= score <= 1.0):
        return
    router = get_smart_router()
    if hasattr(router, "send_feedback"):
        await router.send_feedback(inference_id, "response_quality", score)
