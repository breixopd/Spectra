"""
Command Tool Adapter.

Provides command building and output parsing for security tools.
Execution is handled by the ARQ worker in the tools container.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.tools.adapter.base import ToolAdapter, ToolExecutionError
from app.services.tools.adapter.builder import CommandBuilder
from app.services.tools.adapter.parser import OutputParser
from app.services.tools.models import (
    ToolConfig,
    ToolExecutionRequest,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("spectra.tools.adapter")

__all__ = [
    "CommandToolAdapter",
    "ToolExecutionError",
    "CommandBuilder",
    "OutputParser",
    "create_adapter",
]


class CommandToolAdapter(ToolAdapter):
    """
    Generic adapter for security tools.

    This adapter handles:
    - Building commands with templated arguments
    - Parsing output based on tool configuration

    Actual execution is delegated to the ARQ worker in the tools container.
    """

    def __init__(self, config: ToolConfig) -> None:
        super().__init__(config)
        self.builder = CommandBuilder(config)
        self.parser = OutputParser(config)

    def build_command(
        self,
        request: ToolExecutionRequest,
        output_dir: str | Path | None = None,
    ) -> str:
        """
        Build the command string for execution.

        Args:
            request: Tool execution request with target and args.
            output_dir: Directory for output files.

        Returns:
            Command string ready for execution.
        """
        return self.builder.build_command(request, output_dir)

    def calculate_timeout(self, request: ToolExecutionRequest) -> int:
        """Calculate dynamic timeout based on target and tool config."""
        exec_config = self.config.execution

        if request.timeout:
            return min(request.timeout, exec_config.max_timeout)

        base_timeout = exec_config.timeout
        target = request.target
        host_count = 1

        if "/" in target:
            try:
                import ipaddress

                network = ipaddress.ip_network(target, strict=False)
                host_count = min(network.num_addresses, 256)
            except ValueError:
                pass

        dynamic_timeout = exec_config.timeout_per_host * host_count
        calculated = max(base_timeout, dynamic_timeout)

        return max(exec_config.min_timeout, min(calculated, exec_config.max_timeout))


def create_adapter(config: ToolConfig) -> ToolAdapter:
    """Create a tool adapter from a configuration."""
    return CommandToolAdapter(config)
