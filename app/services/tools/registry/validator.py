from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.services.tools.models import OutputFormat, ToolConfig
from app.services.tools.registry.constants import DANGEROUS_PATTERNS
from app.services.tools.registry.exceptions import (
    PluginSignatureError,
    PluginValidationError,
)

# Supported plugin schema versions
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "1.1.0", "1.2.0"}

# Shell injection patterns beyond the command blocklist
_SHELL_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\$\{.*\}"),  # ${...} variable expansion
    re.compile(r"\$\([^)]+\)"),  # $(...) command substitution
    re.compile(r"`[^`]+`"),  # backtick substitution
    re.compile(r"\|\s*\w+"),  # pipe to another command
    re.compile(r";\s*\w+"),  # semicolon chaining
    re.compile(r"&&\s*\w+"),  # && chaining
    re.compile(r"\|\|\s*\w+"),  # || chaining
    re.compile(r">\s*/"),  # redirect to root
    re.compile(r"\beval\b"),  # eval usage
    re.compile(r"\bexec\b"),  # exec usage
    re.compile(r"\bsource\b"),  # source usage
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
                raise PluginSignatureError("Plugin has no signature and safe_mode is enabled")
            if not self._public_key:
                raise PluginSignatureError("No public key configured for signature verification")
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

        # Validate schema version
        self._validate_schema_version(config)

        # Validate command format for shell injection
        self._validate_command_format(config)

        # Validate output parser configuration
        self._validate_output_parser(config)

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
            canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

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
                    raise PluginValidationError(f"Dangerous command pattern detected: {pattern.pattern}")

    def _validate_schema_version(self, config: ToolConfig) -> None:
        """Validate the plugin schema version is supported."""
        version = config.version
        # Parse major.minor for compatibility (allow any patch)
        parts = version.split(".")
        if len(parts) != 3:
            raise PluginValidationError(f"Invalid version format: {version}")
        try:
            major, _minor = int(parts[0]), int(parts[1])
        except ValueError:
            raise PluginValidationError(f"Invalid version format: {version}")
        # Accept any version with major=1 (forward-compatible within v1.x.x)
        if major < 1:
            raise PluginValidationError(f"Unsupported schema version: {version} (minimum 1.0.0)")
        if major > 1:
            logger.warning(
                "Plugin '%s' uses schema version %s which may not be fully supported",
                config.id,
                version,
            )

    def _validate_command_format(self, config: ToolConfig) -> None:
        """Validate command and args_template for shell injection patterns."""
        # The base command should be a simple executable name
        command = config.execution.command
        if not command or not command.strip():
            raise PluginValidationError("Execution command cannot be empty")

        # Check the base command for injection patterns
        for pattern in _SHELL_INJECTION_PATTERNS:
            if pattern.search(command):
                raise PluginValidationError(f"Shell injection pattern in command '{command}': {pattern.pattern}")

        # Check args_template for injection patterns
        args_template = config.execution.args_template
        if args_template:
            # Allow {placeholder} patterns and quoted strings (tool-specific syntax)
            # Strip out valid placeholders and quoted content first
            cleaned = re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "", args_template)
            cleaned = re.sub(r"'[^']*'", "", cleaned)
            cleaned = re.sub(r'"[^"]*"', "", cleaned)
            cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)  # optional arg brackets
            for pattern in _SHELL_INJECTION_PATTERNS:
                if pattern.search(cleaned):
                    raise PluginValidationError(f"Shell injection pattern in args_template: {pattern.pattern}")

    def _validate_output_parser(self, config: ToolConfig) -> None:
        """Validate the output parsing configuration."""
        parsing = config.parsing

        # Validate format-specific requirements
        if parsing.format in (OutputFormat.JSON, OutputFormat.NDJSON, OutputFormat.XML, OutputFormat.CSV):
            # Structured formats should have field mapping for best results
            if not parsing.mapping:
                logger.info(
                    "Plugin '%s' uses %s format without field mapping — raw fields will be used",
                    config.id,
                    parsing.format,
                )

        # Validate regex patterns
        for i, pattern_config in enumerate(parsing.regex_patterns):
            pattern_str = pattern_config.get("pattern")
            if not pattern_str:
                raise PluginValidationError(f"Regex pattern {i} missing 'pattern' field")
            if len(pattern_str) > 500:
                raise PluginValidationError(f"Regex pattern {i} exceeds max length (500 chars)")
            try:
                re.compile(pattern_str)
            except re.error as e:
                raise PluginValidationError(f"Invalid regex pattern {i}: {e}") from e

        # Validate jq filter syntax (basic check)
        if parsing.jq_filter:
            jq = parsing.jq_filter
            if any(c in jq for c in (";", "|", "&", "`", "$(")):
                # jq filters can legitimately contain | for pipes, but not shell operators
                # Only flag obvious shell injection
                if ";" in jq or "&&" in jq or "`" in jq or "$(" in jq:
                    raise PluginValidationError(f"Suspicious characters in jq_filter: {jq}")
