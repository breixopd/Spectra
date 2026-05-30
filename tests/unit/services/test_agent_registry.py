"""Tests for Agent Registry and Factory pattern."""

import logging
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from spectra_ai_core.agents.base import (
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from spectra_ai_core.agents.registry import (
    AgentRegistry,
    _registry,
    get_agent_registry,
    register_agent,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _DummyInput(BaseModel):
    value: str = "test"


class _DummyOutput(AgentAction):
    action_type: str = "test"
    confidence: float = 0.9
    risk_level: str = "low"
    reasoning: str = "test"


def _make_agent_class(agent_role: AgentRole, agent_name: str = "Dummy") -> type[Agent[Any, Any]]:
    """Dynamically build a minimal concrete Agent subclass."""

    _role = agent_role
    _name = agent_name

    class _Cls(Agent[_DummyInput, _DummyOutput]):
        role: ClassVar[AgentRole] = _role  # type: ignore[assignment]
        name: ClassVar[str] = _name
        description: ClassVar[str] = f"{_name} agent"

        async def execute(self, context: AgentContext, input_data: _DummyInput) -> AgentResult:
            return AgentResult(success=True, action=_DummyOutput())

    _Cls.__name__ = agent_name
    _Cls.__qualname__ = agent_name
    return _Cls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Stash the real registry content so tests that mutate it can restore it.


@pytest.fixture(autouse=True)
def _preserve_registry():
    """Snapshot/restore the global registry around every test."""
    snapshot = dict(_registry)
    yield
    _registry.clear()
    _registry.update(snapshot)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_agent_decorator():
    """Decorator registers a dummy agent class."""
    cls = _make_agent_class(AgentRole.SCOPE, "DummyScope")
    registered = register_agent(cls)
    assert registered is cls
    assert _registry[AgentRole.SCOPE] is cls


def test_registry_create_agent():
    """Factory creates instance with LLM."""
    cls = _make_agent_class(AgentRole.SCOPE, "CreateTest")
    register_agent(cls)

    registry = AgentRegistry()
    mock_llm = MagicMock()
    agent = registry.create(AgentRole.SCOPE, mock_llm)

    assert isinstance(agent, cls)
    assert agent.llm is mock_llm


def test_registry_get_class():
    """Returns correct class for a role."""
    cls = _make_agent_class(AgentRole.SCOPE, "GetClassTest")
    register_agent(cls)

    registry = AgentRegistry()
    assert registry.get_class(AgentRole.SCOPE) is cls


def test_registry_has():
    """True for registered, False for unregistered."""
    cls = _make_agent_class(AgentRole.SCOPE, "HasTest")
    register_agent(cls)

    registry = AgentRegistry()
    assert registry.has(AgentRole.SCOPE) is True
    # Clear to test absence
    _registry.pop(AgentRole.SCOPE, None)
    assert registry.has(AgentRole.SCOPE) is False


def test_registry_list_agents():
    """Lists all registered agents with correct metadata."""
    _registry.clear()
    cls_a = _make_agent_class(AgentRole.SCOPE, "ListA")
    cls_b = _make_agent_class(AgentRole.PARSER, "ListB")
    register_agent(cls_a)
    register_agent(cls_b)

    infos = AgentRegistry().list_agents()
    assert len(infos) == 2
    names = {i.name for i in infos}
    assert names == {"ListA", "ListB"}
    for info in infos:
        assert info.cls is not None
        assert info.description


def test_registry_overwrite_warning(caplog):
    """Registering same role twice logs warning."""
    cls_a = _make_agent_class(AgentRole.SCOPE, "First")
    cls_b = _make_agent_class(AgentRole.SCOPE, "Second")

    register_agent(cls_a)
    with caplog.at_level(logging.WARNING, logger="spectra.ai.agents.registry"):
        register_agent(cls_b)

    assert any("Overwriting" in m for m in caplog.messages)
    assert _registry[AgentRole.SCOPE] is cls_b


def test_registry_missing_role_raises():
    """KeyError for unregistered role."""
    _registry.clear()
    registry = AgentRegistry()
    with pytest.raises(KeyError, match="No agent registered"):
        registry.get_class(AgentRole.PARSER)


def test_all_agents_registered():
    """All 12 concrete agent modules register themselves."""
    # Force every agent module to import (triggers @register_agent)

    expected_roles = {
        AgentRole.DEBRIEF,
        AgentRole.EXPLOIT_CRAFTER,
        AgentRole.EXPLOIT_VERIFIER,
        AgentRole.MISSION_CONTROLLER,
        AgentRole.POC_DEVELOPER,
        AgentRole.POST_EXPLOITATION,
        AgentRole.RECON_INTEL,
        AgentRole.REPORTER,
        AgentRole.SAFETY_SUPERVISOR,
        AgentRole.SCOPE,
        AgentRole.TOOL_SELECTOR,
        AgentRole.VECTOR_GENERATOR,
    }

    registered_roles = set(_registry.keys())
    missing = expected_roles - registered_roles
    assert not missing, f"Missing agent registrations: {missing}"
    assert len(expected_roles) == 12


def test_get_agent_registry_singleton():
    """get_agent_registry returns the same instance."""
    assert get_agent_registry() is get_agent_registry()
