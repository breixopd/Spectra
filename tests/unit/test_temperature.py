import pytest

from app.services.ai.agents.base import Agent, AgentResult, AgentRole
from tests.mocks.llm import MockLLMClient


class ScopeAgent(Agent):
    role = AgentRole.SCOPE
    name = "ScopeAgent"
    description = "Scope Agent"

    async def execute(self, context, input_data):
        return AgentResult(success=True)


class ExploitAgent(Agent):
    role = AgentRole.EXPLOIT_CRAFTER
    name = "ExploitAgent"
    description = "Exploit Agent"

    async def execute(self, context, input_data):
        return AgentResult(success=True)


class MissionAgent(Agent):
    role = AgentRole.MISSION_CONTROLLER
    name = "MissionAgent"
    description = "Mission Agent"

    async def execute(self, context, input_data):
        return AgentResult(success=True)


@pytest.mark.asyncio
async def test_temperature_control():
    """Test that temperature is correctly passed to the LLM."""
    mock_llm = MockLLMClient()

    # Test Low Temp (Scope)
    scope_agent = ScopeAgent(mock_llm)
    assert scope_agent._get_temperature(None) == 0.1

    # Test High Temp (Exploit)
    exploit_agent = ExploitAgent(mock_llm)
    assert exploit_agent._get_temperature(None) == 0.7

    # Test Medium Temp (Mission)
    mission_agent = MissionAgent(mock_llm)
    assert mission_agent._get_temperature(None) == 0.4


@pytest.mark.asyncio
async def test_llm_temperature_param():
    """Test that LLM client receives the temperature parameter."""
    mock_llm = MockLLMClient()

    await mock_llm.generate("test", temperature=0.8)
    assert mock_llm.call_history[-1]["temperature"] == 0.8

    await mock_llm.generate("test", temperature=0.1)
    assert mock_llm.call_history[-1]["temperature"] == 0.1
