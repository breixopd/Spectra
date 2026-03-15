"""Agent Registry — auto-discovers and instantiates agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services.ai.agents.base import Agent, AgentRole

if TYPE_CHECKING:
    from app.services.ai.llm import LLMClient

logger = logging.getLogger(__name__)

_registry: dict[AgentRole, type[Agent[Any, Any]]] = {}


@dataclass(frozen=True)
class AgentInfo:
    """Metadata about a registered agent."""

    name: str
    role: AgentRole
    description: str
    cls: type[Agent[Any, Any]]


def register_agent(cls: type[Agent[Any, Any]]) -> type[Agent[Any, Any]]:
    """Class decorator that registers an agent in the global registry."""
    role: AgentRole = cls.role  # type: ignore[assignment]
    if role in _registry:
        logger.warning(
            "Overwriting agent for role %s: %s -> %s",
            role,
            _registry[role].__name__,
            cls.__name__,
        )
    _registry[role] = cls
    logger.debug("Registered agent %s for role %s", cls.__name__, role)
    return cls


class AgentRegistry:
    """Singleton facade over the module-level agent registry."""

    def register(self, cls: type[Agent[Any, Any]]) -> None:
        """Register an agent class by its AgentRole."""
        register_agent(cls)

    def create(self, role: AgentRole, llm: LLMClient) -> Agent[Any, Any]:
        """Factory: instantiate an agent by role."""
        cls = self.get_class(role)
        return cls(llm)

    def get_class(self, role: AgentRole) -> type[Agent[Any, Any]]:
        """Return the agent class for a role."""
        try:
            return _registry[role]
        except KeyError:
            raise KeyError(f"No agent registered for role {role!r}") from None

    def list_agents(self) -> list[AgentInfo]:
        """List all registered agents with metadata."""
        return [
            AgentInfo(
                name=cls.name,
                role=role,
                description=cls.description,
                cls=cls,
            )
            for role, cls in _registry.items()
        ]

    def has(self, role: AgentRole) -> bool:
        """Check if a role is registered."""
        return role in _registry


_instance = AgentRegistry()
_all_imported = False


def _ensure_all_agents_imported() -> None:
    """Import every agent module so their @register_agent decorators fire."""
    global _all_imported  # noqa: PLW0603
    if _all_imported:
        return
    import importlib

    _agent_modules = [
        "app.services.ai.agents.scope",
        "app.services.ai.agents.tool_selector",
        "app.services.ai.agents.mission_controller",
        "app.services.ai.agents.safety",
        "app.services.ai.agents.exploit_crafter",
        "app.services.ai.agents.exploit_verifier",
        "app.services.ai.agents.poc_developer",
        "app.services.ai.agents.post_exploitation",
        "app.services.ai.agents.vector_generator",
        "app.services.ai.agents.debrief",
        "app.services.ai.agents.reporter",
        "app.services.ai.agents.recon_intel",
    ]
    for mod_name in _agent_modules:
        try:
            importlib.import_module(mod_name)
        except (OSError, RuntimeError, ImportError):
            logger.debug("Could not import agent module: %s", mod_name)
    _all_imported = True
    logger.debug("Agent registry: %d agents registered", len(_registry))


def get_agent_registry() -> AgentRegistry:
    """Return the singleton AgentRegistry, ensuring all agents are loaded."""
    _ensure_all_agents_imported()
    return _instance
