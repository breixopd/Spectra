from __future__ import annotations

import logging
from abc import ABC
from pathlib import Path

from app.services.tools.models import (
    ToolConfig,
    ToolExecutionRequest,
)

logger = logging.getLogger(__name__)

class ToolExecutionError(Exception):
    """Raised when tool execution fails."""

    pass


class ToolAdapter(ABC):
    """Abstract base class for tool adapters.

    Note: Actual execution is handled by the ARQ worker in the tools container.
    Adapters are used for command building and output parsing only.
    """

    def __init__(self, config: ToolConfig) -> None:
        """Initialize the adapter with a tool configuration.

        Args:
            config: The tool's plugin configuration.
        """
        self.config = config

    def build_command(
        self,
        request: ToolExecutionRequest,
        output_dir: str | Path | None = None,
    ) -> str:
        """Build the command string for execution.

        Args:
            request: Execution request with target and args.
            output_dir: Directory for output files.

        Returns:
            Command string ready for execution.
        """
        raise NotImplementedError("Subclasses must implement build_command")
