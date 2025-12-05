"""Business logic services for the Spectra Security Assessment Platform.

This package contains:
- AI services (LLM clients, agents, consensus, RAG)
- Mission orchestration (planning, execution, management)
- Tool management (registry, adapters, execution)

Architecture follows SOLID principles:
- Single Responsibility: Each service has one clear purpose
- Open/Closed: Services are extensible via agents/plugins
- Liskov Substitution: LLM clients implement common interface
- Interface Segregation: Agents have focused interfaces
- Dependency Inversion: Services depend on abstractions (LLMClient, etc.)
"""

# Note: Import specific services directly from their submodules
# to avoid circular imports:
#
# from app.services.ai import LLMClient, VotingSystem
# from app.services.mission import MissionManager, mission_manager
# from app.services.tools import ToolRegistry, get_registry
