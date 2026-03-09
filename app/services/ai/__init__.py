"""
AI Services package for the MAKER Framework.

Contains:
- LLM clients (LiteLLM smart router, Mock) — all providers unified through LiteLLM
- Agent swarm architecture (scope, tool selector, exploit, safety, etc.)
- Consensus engine (K-threshold voting system)
- Persistent memory (cross-mission learning)
- Playbook engine (deterministic attack patterns)
- CVE intelligence (version-to-exploit correlation)
- Grounding framework (anti-hallucination)
- RAG engine (knowledge retrieval via PostgreSQL)
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
    LLMClient,
    LLMResponse,
    get_llm_client,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "get_llm_client",
    "VotingSystem",
    "VotingConfig",
    "Vote",
    "VoteDecision",
    "ConsensusResult",
    "ConsensusStatus",
]
