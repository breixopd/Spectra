from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.mission import Mission
from app.services.ai.agents.mission_controller import AssessmentPhase, Task
from app.services.mission.executor import MissionExecutor
from spectra_ai.llm import LLMClient


@pytest.fixture
def mock_llm():
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def executor(mock_llm):
    # Initialize real executor
    return MissionExecutor(mock_llm)


@pytest.fixture
def mission():
    m = MagicMock(spec=Mission)
    m.id = "mission-core-test"
    m.target = "example.com"
    m.log = MagicMock()
    return m


@pytest.mark.asyncio
async def test_execute_task_success(executor, mission):
    """Test task execution flow."""
    task = Task(
        task_id="t1",
        description="scan",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )
    context = MagicMock()

    # Mock dispatcher
    executor.dispatcher = AsyncMock()

    await executor.execute_task(mission, task, context)

    executor.dispatcher.dispatch.assert_called_once_with(mission, task, context)


@pytest.mark.asyncio
async def test_execute_task_failure(executor, mission):
    """Test task execution failure handling."""
    task = Task(
        task_id="t1",
        description="scan",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )
    context = MagicMock()

    executor.dispatcher = AsyncMock()
    executor.dispatcher.dispatch.side_effect = RuntimeError("Dispatch failed")

    with pytest.raises(RuntimeError):
        await executor.execute_task(mission, task, context)

    mission.log.assert_called()
