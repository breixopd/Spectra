from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any

from app.services.tools.models import ToolConfig, ToolExecutionRequest

logger = logging.getLogger(__name__)

_FLAG_ARG_KEYS = {"flags", "extra_flags", "extra_args"}
_UNSAFE_FLAG_CHARS = set(";&|`$><\n\r")


class CommandBuilder:
    """Handles command construction and argument templating."""

    def __init__(self, config: ToolConfig):
        self.config = config

    def build_command(
        self,
        request: ToolExecutionRequest,
        output_dir: str | Path | None = None,
    ) -> str:
        """Build the full command string from the template.

        Handles:
            - Template substitution
            - Arg modifiers (prefix, separator)
            - Cleaning up unused placeholders
            - Collapsing extra spaces

        Args:
            request: The execution request containing target and args.
            output_dir: Optional directory for output files.

        Returns:
            The fully constructed command string.
        """
        base_cmd = self.config.execution.command
        args_template = self.config.execution.args_template

        # Apply arg_modifiers to request args
        processed_args = self._apply_arg_modifiers(request.args)

        # Prepare substitution values - target is protected from override
        substitutions = {
            **processed_args,  # User args first (with modifiers applied)
            "target": request.target,  # Target always wins (security)
        }

        # Handle output file requirement
        if "{output_file}" in args_template:
            if not output_dir:
                raise ValueError(f"Tool {self.config.id} requires output_dir for {{output_file}} template")

            output_path = Path(output_dir) / f"{self.config.id}_output"
            substitutions["output_file"] = str(output_path)
        else:
            substitutions["output_file"] = ""

        # Process conditional blocks first
        # Blocks like [set PORT {port}] are removed if {port} is missing/empty
        args = self._process_conditional_blocks(args_template, substitutions)

        # Substitute provided values
        for key, value in substitutions.items():
            placeholder = "{" + key + "}"
            if value is None:
                value = ""

            str_value = str(value)

            # Skip empty values - they'll be removed by the placeholder regex below
            if not str_value.strip():
                continue

            if key in _FLAG_ARG_KEYS:
                safe_value = self._quote_flag_fragment(str_value)
            # Handle values that have flag prefixes (from arg_modifiers)
            # e.g., "-t cves/,vulnerabilities/" should become: -t 'cves/,vulnerabilities/'
            elif str_value.startswith("-") and " " in str_value:
                # Split into flag and value parts
                flag_end = str_value.index(" ")
                flag = str_value[:flag_end]
                rest = str_value[flag_end + 1 :]
                safe_value = f"{flag} {shlex.quote(rest)}"
            else:
                # Use shlex.quote to prevent command injection
                safe_value = shlex.quote(str_value)

            args = args.replace(placeholder, safe_value)

        # Remove any remaining placeholders (e.g., {flags} if not provided)
        args = re.sub(r"\{[a-zA-Z0-9_]+\}", "", args)

        # Collapse multiple spaces
        args = re.sub(r"\s+", " ", args).strip()

        # Build full command
        command = f"{base_cmd} {args}".strip()

        return command

    def _quote_flag_fragment(self, value: str) -> str:
        """Split a free-form flags field into safe shell tokens."""
        tokens = shlex.split(value)
        for token in tokens:
            if any(char in token for char in _UNSAFE_FLAG_CHARS):
                raise ValueError(f"Unsafe flag token rejected: {token[:40]}")
        return " ".join(shlex.quote(token) for token in tokens)

    def apply_stealth_args(self, command: str, stealth_config: Any) -> str:
        """Apply stealth mode extra_args to the built command.

        Appends stealth arguments (e.g., rate-limit flags) that the tool
        supports. Skips args that are already present in the command.
        """
        if not stealth_config or not stealth_config.extra_args:
            return command

        for flag, value in stealth_config.extra_args.items():
            # Don't duplicate flags already in the command
            if flag in command:
                continue
            if value and str(value).lower() not in ("true", ""):
                safe_value = shlex.quote(str(value))
                command = f"{command} {flag} {safe_value}"
            else:
                command = f"{command} {flag}"

        return command

    def _apply_arg_modifiers(self, args: dict) -> dict:
        """Apply arg_modifiers from tool config to transform argument values.

        Example:
            args = {"extensions": "php,html,txt"}
            arg_modifiers = {"extensions": {"prefix": "-x ", "separator": ","}}
            Result: {"extensions": "-x php,html,txt"}
        """
        if not self.config.execution.arg_modifiers:
            return args

        result = dict(args)

        for arg_name, modifier in self.config.execution.arg_modifiers.items():
            if arg_name not in result:
                continue

            value = str(result[arg_name]).strip()

            # Skip empty or placeholder values
            if not value or value in ("", "None", "null", "-t", "-x", "-tags"):
                # Remove the empty arg so it won't appear in the command
                del result[arg_name]
                continue

            # Strip any existing prefix if it was mistakenly added by LLM
            prefix = modifier.get("prefix", "")
            if prefix and value.startswith(prefix.strip()):
                value = value[len(prefix.strip()) :].strip()

            # Skip if after stripping prefix, value is empty
            if not value:
                del result[arg_name]
                continue

            # Apply separator if needed (normalize whitespace to separator)
            separator = modifier.get("separator")
            if separator and " " in value and separator != " ":
                value = value.replace(" ", separator)

            # Apply prefix
            if prefix:
                # Ensure there's a space after flag-style prefixes
                if prefix.startswith("-") and not prefix.endswith(" "):
                    value = f"{prefix} {value}"
                else:
                    value = f"{prefix}{value}"

            result[arg_name] = value

        return result

    def _process_conditional_blocks(self, template: str, substitutions: dict[str, Any]) -> str:
        """Process conditional blocks in the template.

        Format: [content {placeholder} content]
        If all placeholders in the block are present in substitutions and non-empty,
        the block is kept (without brackets). Otherwise, it is removed.
        """

        def replace_block(match):
            block_content = match.group(1)
            # Find all placeholders in the block
            placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", block_content)

            # Check if all placeholders have valid values
            for key in placeholders:
                val = substitutions.get(key)
                if val is None or str(val).strip() == "":
                    return ""

            return block_content

        # Match [...] blocks
        # Regex: \[([^\]]+)\]
        return re.sub(r"\[([^\]]+)\]", replace_block, template)
