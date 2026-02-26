import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.mission.executor import MissionExecutor
from app.services.ai.agents.base import ToolAction, AgentContext
from app.services.mission.mission import Mission
from app.models.attack_surface import ExploitAttempt, VectorPriority, AttackVector
from app.services.ai.llm import LLMClient


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
