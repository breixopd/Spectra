from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.services.tools.models import ToolConfig
from app.services.tools.registry.constants import DANGEROUS_PATTERNS
from app.services.tools.registry.exceptions import (
    PluginSignatureError,
    PluginValidationError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("spectra.tools.registry.validator")

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519 as crypto_ed25519_mod

    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False
    crypto_ed25519_mod = None  # type: ignore


class PluginValidator:
    """Validator for tool plugins."""

    def __init__(self, public_key: Any | None = None, safe_mode: bool = True):
        self._public_key = public_key
        self.safe_mode = safe_mode

    def validate_plugin(self, data: dict[str, Any]) -> ToolConfig:
        """Validate a plugin configuration.

        Checks:
            1. JSON schema (via Pydantic)
            2. Signature (if safe_mode is enabled)
            3. Command safety (blocklist check)

        Args:
            data: Raw plugin data dictionary. Not modified.

        Returns:
            Validated ToolConfig.

        Raises:
            PluginValidationError: If validation fails.
            PluginSignatureError: If signature is invalid.
        """
        # Extract signature without mutating input
        signature_hex = data.get("signature")

        # Create a copy without signature for validation
        validation_data = {k: v for k, v in data.items() if k != "signature"}

        # Check signature if safe mode
        if self.safe_mode:
            if not signature_hex:
                raise PluginSignatureError(
                    "Plugin has no signature and safe_mode is enabled"
                )
            if not self._public_key:
                raise PluginSignatureError(
                    "No public key configured for signature verification"
                )
            self._verify_signature(validation_data, signature_hex)

        # Validate schema
        try:
            config = ToolConfig.model_validate(validation_data)
        except Exception as e:
            raise PluginValidationError(f"Invalid plugin schema: {e}") from e

        # Restore signature
        config.signature = signature_hex

        # Validate commands
        self._validate_commands(config)

        # Validate ID format
        if not re.match(r"^[a-zA-Z0-9_-]+$", config.id):
            raise PluginValidationError(f"Invalid tool ID format: {config.id}")

        return config

    def _verify_signature(self, data: dict[str, Any], signature_hex: str) -> None:
        """Verify the Ed25519 signature of a plugin."""
        if not _HAS_CRYPTOGRAPHY:
            raise PluginSignatureError("cryptography package not installed")

        try:
            if not _HAS_CRYPTOGRAPHY or crypto_ed25519_mod is None:
                raise PluginSignatureError("cryptography package not available")

            # Check if public key is of correct type (we skip strict type check to avoid import issues if not installed)
            if not getattr(self._public_key, "verify", None):
                raise PluginSignatureError("Invalid public key type")

            # Canonicalize JSON (same as sign_plugin.py)
            canonical_json = json.dumps(
                data, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")

            # Validate hex string before conversion
            try:
                signature = bytes.fromhex(signature_hex)
            except ValueError as e:
                raise PluginSignatureError(f"Invalid signature hex: {e}") from e

            self._public_key.verify(signature, canonical_json)

        except PluginSignatureError:
            raise
        except Exception as e:
            raise PluginSignatureError(f"Signature verification failed: {e}") from e

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
                    raise PluginValidationError(
                        f"Dangerous command pattern detected: {pattern.pattern}"
                    )
