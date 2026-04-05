"""
Command Tool Adapter.

Provides command building, output parsing, and execution for security tools.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.constants import MAX_HOSTS_DEFAULT
from app.core.telemetry import record_tool_execution
from app.services.tools.adapter.base import ToolAdapter, ToolExecutionError
from app.services.tools.adapter.builder import CommandBuilder
from app.services.tools.adapter.parser import OutputParser
from app.services.tools.models import (
    ToolConfig,
    ToolExecutionRequest,
    ToolExecutionResult,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

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
    - Wrapping commands with timeout and optional Docker execution
    - Parsing output based on tool configuration
    - Full async execution with timeout handling
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

        Builds the raw command, wraps it with a timeout, and optionally
        wraps with ``docker exec`` when a container is configured.

        Args:
            request: Tool execution request with target and args.
            output_dir: Directory for output files.

        Returns:
            Command string ready for execution.
        """
        from app.services.tools.adapter import runner

        raw_cmd = self.builder.build_command(request, output_dir)
        timeout = self.calculate_timeout(request)

        wrapped_cmd = f"timeout -k 5s {timeout}s {raw_cmd}"

        return wrapped_cmd

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
                host_count = min(network.num_addresses, MAX_HOSTS_DEFAULT)
            except ValueError:
                pass

        dynamic_timeout = exec_config.timeout_per_host * host_count
        calculated = max(base_timeout, dynamic_timeout)

        return max(exec_config.min_timeout, min(calculated, exec_config.max_timeout))

    async def execute(
        self,
        request: ToolExecutionRequest,
        output_dir: str | Path | None = None,
    ) -> ToolExecutionResult:
        """Execute the tool command.

        Args:
            request: Tool execution request with target and args.
            output_dir: Optional directory for output files.

        Returns:
            ToolExecutionResult with stdout/stderr and parsed findings.

        Raises:
            ValueError: If the request target is empty.
        """
        if not request.target:
            raise ValueError("target cannot be empty")

        cmd = self.build_command(request, output_dir)
        timeout = self.calculate_timeout(request)

        start_time = time.time()

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)
            duration = time.time() - start_time

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            parsed: list = []
            try:
                parsed = await self.parser.parse_output(
                    stdout,
                    stderr,
                    str(Path(output_dir) / f"{self.config.id}_output") if output_dir else None,
                )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Failed to parse tool output: %s", e)

            success = proc.returncode == 0

            # Exit code 124 is produced by the `timeout` coreutils wrapper
            if proc.returncode == 124 and not stderr:
                stderr = f"Command timed out after {timeout}s"
                success = False

            await record_tool_execution(
                tool_id=request.tool_id,
                duration_ms=duration * 1000,
                success=success,
            )

            return ToolExecutionResult(
                tool_id=request.tool_id,
                target=request.target,
                success=success,
                exit_code=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                output_file=str(Path(output_dir) / f"{self.config.id}_output") if output_dir else None,
                parsed_findings=parsed,
            )
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError as e:
                logger.debug("Failed to kill process group: %s", e)
            timeout_duration = time.time() - start_time
            await record_tool_execution(
                tool_id=request.tool_id,
                duration_ms=timeout_duration * 1000,
                success=False,
            )
            return ToolExecutionResult(
                tool_id=request.tool_id,
                target=request.target,
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_seconds=timeout_duration,
            )


def create_adapter(config: ToolConfig) -> ToolAdapter:
    """Create a tool adapter from a configuration."""
    return CommandToolAdapter(config)
