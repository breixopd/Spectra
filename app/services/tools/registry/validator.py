from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from app.services.tools.models import ToolConfig
from spectra_tools_core.registry_constants import DANGEROUS_PATTERNS
from spectra_tools_core.registry_exceptions import PluginValidationError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PluginValidator:
    """Validator for tool plugins."""

    def __init__(self):
        pass

    def validate_plugin(self, data: dict[str, Any]) -> ToolConfig:
        """Validate a plugin configuration.

        Checks:
            1. JSON schema (via Pydantic)
            2. Command safety (blocklist check)

        Args:
            data: Raw plugin data dictionary. Not modified.

        Returns:
            Validated ToolConfig.

        Raises:
            PluginValidationError: If validation fails.
        """
        # Validate schema
        try:
            config = ToolConfig.model_validate(data)
        except (ValueError, TypeError, KeyError) as e:
            raise PluginValidationError(f"Invalid plugin schema: {e}") from e

        # Validate commands
        self._validate_commands(config)

        # Validate ID format
        if not re.match(r"^[a-zA-Z0-9_-]+$", config.id):
            raise PluginValidationError(f"Invalid tool ID format: {config.id}")

        return config

    def _validate_commands(self, config: ToolConfig) -> None:
        """Check installation and execution commands against the blocklist."""
        # Check both installation and verification commands
        commands: list[str] = list(config.installation.commands)
        if config.installation.verification_command:
            commands.append(config.installation.verification_command)

        # Check uninstall commands too!
        if config.installation.uninstall_commands:
            commands.extend(config.installation.uninstall_commands)

        # Check execution command
        if config.execution.command:
            commands.append(config.execution.command)

        for cmd in commands:
            # Skip empty commands
            if not cmd or not cmd.strip():
                continue
            for pattern in DANGEROUS_PATTERNS:
                if pattern.search(cmd):
                    raise PluginValidationError(f"Dangerous command pattern detected: {pattern.pattern}")
