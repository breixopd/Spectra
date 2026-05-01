"""
AI orchestration package (MAKER framework).

Runtime primitives (LLM, router, embeddings, RAG, prompts, etc.) live in
``spectra_ai``. This package keeps mission agents, consensus, memory, and other
parts tightly coupled to app models and mission lifecycle.
"""

from spectra_ai.llm import (
    LLMClient,
    LLMResponse,
    get_llm_client,
)
from spectra_platform.services.ai.consensus import (
    ConsensusResult,
    ConsensusStatus,
    Vote,
    VoteDecision,
    VotingConfig,
    VotingSystem,
)

__all__ = [
    "ConsensusResult",
    "ConsensusStatus",
    "LLMClient",
    "LLMResponse",
    "Vote",
    "VoteDecision",
    "VotingConfig",
    "VotingSystem",
    "get_llm_client",
]
