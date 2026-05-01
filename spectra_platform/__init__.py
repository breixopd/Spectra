"""
Spectra Security Assessment Platform.

A modular, AI-driven security assessment tool implementing the MAKER Framework
for autonomous penetration testing with human oversight.

Architecture:
- Core: Configuration, database, security, lifecycle management
- Models: SQLAlchemy ORM models (Target, Finding, Exploit, User)
- Repositories: Data access layer with Repository pattern
- Services: Business logic (AI agents, mission orchestration, tool execution)
- HTTP: FastAPI apps live under `services/api/src/spectra_api/` (not in this package)

Key Features:
- Multi-agent AI swarm for assessment automation
- K-threshold consensus voting for risk management
- RAG-augmented knowledge base
- Dynamic tool plugin system with signature verification
- Real-time WebSocket updates
- Iterative exploitation with adaptive replanning
"""

from spectra_platform._meta.version import __version__

__author__ = "Spectra Team"

# Import core explicitly to help with pytest resolution issues
import spectra_platform.core
