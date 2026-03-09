"""
POC Service Module.

Manages the lifecycle of Proof-of-Concept custom exploits.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class POCMetadata(BaseModel):
    """Metadata for a custom POC."""

    name: str
    author: str = "Spectra AI"
    created_at: datetime = Field(default_factory=datetime.now)
    target_service: str
    vulnerability_id: str | None = None
    language: str = "python"
    shell_type: str = "reverse_shell"  # reverse_shell, bind_shell, cmd_exec


class POCRequest(BaseModel):
    """Request to generate a POC."""

    target: str
    vulnerability: dict[str, Any]
    port: int | None = None
    protocol: str = "tcp"
    constraints: list[str] = []


class POCResult(BaseModel):
    """Result of POC generation."""

    success: bool
    content: str | None = None
    metadata: POCMetadata | None = None
    error: str | None = None
