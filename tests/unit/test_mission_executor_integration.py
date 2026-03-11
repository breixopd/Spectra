from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.llm import LLMClient
from app.services.mission.executor import MissionExecutor
from app.services.mission.mission import Mission


@pytest.fixture
def mock_llm():
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def executor(mock_llm):
    return MissionExecutor(mock_llm)


@pytest.fixture
def mission():
    # Use MagicMock for Mission service object as it has complex init
    m = MagicMock(spec=Mission)
    m.id = "test-mission"
    m.target = "example.com"
    m.directive = "Test directive"
    m.log = MagicMock()
    # Mock attack surface
    m.attack_surface = MagicMock()
    m.is_stopped.return_value = False
    return m


class TestMissionExecutorSmoke:
    """Basic smoke tests ensuring MissionExecutor can be instantiated."""

    def test_executor_instantiation(self, executor):
        """Verify the executor fixture creates a valid object."""
        assert executor is not None
        assert isinstance(executor, MissionExecutor)

    def test_executor_has_llm(self, executor, mock_llm):
        """Verify the executor holds a reference to its LLM client."""
        assert executor.llm is mock_llm

    def test_mission_fixture(self, mission):
        """Verify the mission mock has expected attributes."""
        assert mission.id == "test-mission"
        assert mission.target == "example.com"
