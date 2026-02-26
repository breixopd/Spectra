"""
AI Services package for the MAKER Framework.

Contains:
- LLM clients (Ollama, API, Mock) and LiteLLM smart router
- Agent swarm architecture (scope, tool selector, exploit, safety, etc.)
- Consensus engine (K-threshold voting system)
- Persistent memory (cross-mission learning)
- Playbook engine (deterministic attack patterns)
- CVE intelligence (version-to-exploit correlation)
- Grounding framework (anti-hallucination)
- RAG engine (knowledge retrieval via Redis Vector Search)
"""

from app.services.ai.consensus import (
    ConsensusResult,
    ConsensusStatus,
    Vote,
    VoteDecision,
    VotingConfig,
    VotingSystem,
)
from app.services.ai.llm import (
    APIClient,
    LLMClient,
    LLMResponse,
    MockLLMClient,
    OllamaClient,
    get_llm_client,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "OllamaClient",
    "APIClient",
    "MockLLMClient",
    "get_llm_client",
    "VotingSystem",
    "VotingConfig",
    "Vote",
    "VoteDecision",
    "ConsensusResult",
    "ConsensusStatus",
]
