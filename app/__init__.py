"""
Spectra Security Assessment Platform.

A modular, AI-driven security assessment tool implementing the MAKER Framework
for autonomous penetration testing with human oversight.

Architecture:
- Core: Configuration, database, security, lifecycle management
- Models: SQLAlchemy ORM models (Target, Finding, Exploit, User)
- Repositories: Data access layer with Repository pattern
- Services: Business logic (AI agents, mission orchestration, tool execution)
- API: FastAPI routes and Pydantic schemas

Key Features:
- Multi-agent AI swarm for assessment automation
- K-threshold consensus voting for risk management
- RAG-augmented knowledge base
- Dynamic tool plugin system with signature verification
- Real-time WebSocket updates
- Iterative exploitation with adaptive replanning
"""

__version__ = "2026.03.07"
__author__ = "Spectra Team"

# Import core explicitly to help with pytest resolution issues
import app.core
