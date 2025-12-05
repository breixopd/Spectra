"""
AI Services package for the MAKER Framework.

Contains:
- LLM clients (Ollama, OpenAI, Mock)
- Agent swarm architecture
- Consensus engine (voting system)
- RAG engine (knowledge retrieval)
- Knowledge context service (centralized RAG + methodology)
"""

from app.services.ai.consensus import (
    ConsensusResult,
    ConsensusStatus,
    Vote,
    VoteDecision,
    VotingConfig,
    VotingSystem,
)
from app.services.ai.knowledge import (
    PTES_METHODOLOGY,
    close_rag_service,
    get_available_tools_context,
    get_exploit_context,
    get_full_methodology,
    get_methodology_guidance,
    get_mission_context,
    get_rag_service,
    get_tool_usage_context,
    index_exploit_attempt,
)
from app.services.ai.llm import (
    LLMClient,
    LLMResponse,
    MockLLMClient,
    OllamaClient,
    OpenAIClient,
    get_llm_client,
)
from app.services.ai.embeddings import EmbeddingService
from app.services.ai.rag import (
    Document,
    RAGConfig,
    RAGService,
    SearchResult,
)

__all__ = [
    # LLM
    "LLMClient",
    "LLMResponse",
    "OllamaClient",
    "OpenAIClient",
    "MockLLMClient",
    "get_llm_client",
    # Consensus
    "VotingSystem",
    "VotingConfig",
    "Vote",
    "VoteDecision",
    "ConsensusResult",
    "ConsensusStatus",
    # RAG
    "RAGService",
    "RAGConfig",
    "Document",
    "SearchResult",
    "EmbeddingService",
    # Knowledge (centralized)
    "get_rag_service",
    "close_rag_service",
    "get_methodology_guidance",
    "get_full_methodology",
    "get_exploit_context",
    "get_tool_usage_context",
    "get_mission_context",
    "get_available_tools_context",
    "index_exploit_attempt",
    "PTES_METHODOLOGY",
]
