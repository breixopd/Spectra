"""Dynamic Tool Registry Service.

Manages the lifecycle of security tools:
- Loading plugins from the plugins/ directory
- Validating plugin schemas and signatures
- Installing tools in the spectra-tools container
- Providing available tools to AI agents
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

from app.services.tools.models import (
    RegisteredTool,
    ToolConfig,
    ToolStatus,
)

# Re-export exceptions for cleaner imports
from app.services.tools.registry.exceptions import (
    PluginInstallationError,
    PluginSignatureError,
    PluginValidationError,
)
from app.services.tools.registry.installer import PluginInstaller
from app.services.tools.registry.loader import PluginLoader
from app.services.tools.registry.validator import PluginValidator

__all__ = [
    "ToolRegistry",
    "get_registry",
    "initialize_registry",
    "RegisteredTool",
    "ToolConfig",
    "ToolStatus",
    "PluginInstallationError",
    "PluginSignatureError",
    "PluginValidationError",
]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Dynamic Tool Registry for managing security tool plugins.

    Responsibilities:
        - Load plugins from disk
        - Validate plugin schemas and signatures
        - Install tools via shell commands
        - Track tool status (pending, installing, ready, failed)
        - Provide available tools to AI agents
    """

    def __init__(
        self,
        plugins_dir: str | Path = "plugins",
        public_key_path: str | Path | None = None,
        safe_mode: bool = True,
    ) -> None:
        """Initialize the registry."""
        self.plugins_dir = Path(plugins_dir)
        self.public_key_path = Path(public_key_path) if public_key_path else None
        self.safe_mode = safe_mode

        # Registry state
        self._tools: dict[str, RegisteredTool] = {}
        self._lock = asyncio.Lock()

        # Initialize components
        # We load the key here (conceptually, Validator handles it, but we can pass it)
        # Actually Validator needs the key object, let's load it if possible or pass path
        # The Validator takes `public_key`.
        self._public_key = self._load_public_key()

        self.validator = PluginValidator(
            public_key=self._public_key, safe_mode=safe_mode
        )
        self.loader = PluginLoader(
            plugins_dir=self.plugins_dir, validator=self.validator
        )
        self.installer = PluginInstaller()

    def _load_public_key(self) -> Any | None:
        """Load the Ed25519 public key for signature verification."""
        # potential paths to check
        paths_to_check = []
        if self.public_key_path:
            paths_to_check.append(Path(self.public_key_path))

        # Add default locations (Docker inside /app, and local relative)
        paths_to_check.append(Path("/app/keys/plugin_signing.pub"))
        paths_to_check.append(Path("keys/plugin_signing.pub"))

        found_path: Path | None = None
        for path in paths_to_check:
            if path.exists():
                found_path = path
                logger.debug("Found signing key at %s", path)
                break

        if not found_path:
            logger.warning(
                "No plugin signing key found. Searched: %s",
                [str(p) for p in paths_to_check],
            )
            if self.safe_mode:
                logger.warning(
                    "Safe mode is enabled but no key found. Plugin loading will likely fail."
                )
            return None

        # Determine if crypto is available
        try:
            from cryptography.hazmat.primitives import (
                serialization as crypto_serialization,
            )

            with found_path.open("rb") as f:
                key = crypto_serialization.load_pem_public_key(f.read())
            logger.info("Successfully loaded plugin signing key from %s", found_path)
            return key
        except ImportError:
            logger.warning(
                "cryptography package not installed. Signature verification will fail if safe_mode is enabled."
            )
            return None
        except Exception as e:
            logger.error("Failed to load public key from %s: %s", found_path, e)
            return None

    # --- Delegated Methods ---

    async def load_plugins(self) -> dict[str, RegisteredTool]:
        """Scan the plugins directory and load all valid plugins."""
        async with self._lock:
            self._tools = await self.loader.load_plugins(self._tools)
            return self._tools

    def validate_plugin(self, data: dict[str, Any]) -> ToolConfig:
        """Validate a plugin configuration."""
        return self.validator.validate_plugin(data)

    async def install_tool(
        self,
        tool_id: str,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> bool:
        """Install a tool by executing its installation commands."""
        if tool_id not in self._tools:
            raise PluginInstallationError(f"Unknown tool: {tool_id}")

        tool = self._tools[tool_id]
        return await self.installer.install_tool(tool, progress_callback)

    async def uninstall_tool(
        self,
        tool_id: str,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> bool:
        """Uninstall a tool."""
        if tool_id not in self._tools:
            return False

        tool = self._tools[tool_id]

        # Run uninstall commands
        await self.installer.uninstall_tool(tool, self.plugins_dir, progress_callback)

        # Remove plugin file and entry (Registry responsibility)
        path = self.plugins_dir / f"{tool_id}.json"
        try:
            resolved = path.resolve()
            # Security check: ensure within plugins dir
            if resolved.parent == self.plugins_dir.resolve() and resolved.is_file():
                resolved.unlink()
        except (OSError, ValueError) as e:
            logger.warning("Failed to remove plugin file %s: %s", path, e)

        # Remove from memory
        if tool_id in self._tools:
            del self._tools[tool_id]

        return True

    # --- Query Methods (Kept in Facade for state access) ---

    def list_tools(self) -> list[RegisteredTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tool(self, tool_id: str) -> RegisteredTool | None:
        """Get a specific tool by ID (case-insensitive)."""
        if tool_id in self._tools:
            return self._tools[tool_id]

        tool_id_lower = tool_id.lower()
        if tool_id_lower in self._tools:
            return self._tools[tool_id_lower]

        return None

    def get_available_tools(self) -> list[RegisteredTool]:
        """Get all tools that are ready to use."""
        return [t for t in self._tools.values() if t.is_available]

    async def sync_status_from_cache(self) -> int:
        """
        Sync tool status from cache (set by tools container worker).

        Returns:
            Number of tools updated.
        """
        from app.core.cache import get_cache

        cache = get_cache()
        if not cache:
            logger.warning("Cache not available for status sync")
            return 0

        updated = 0
        for tool_id, tool in self._tools.items():
            try:
                key = f"spectra:tool_status:{tool_id}"
                status_data = await cache.get(key)
            except Exception as e:
                logger.debug("Failed to get status for %s: %s", tool_id, e)
                continue

            if not status_data or not isinstance(status_data, dict):
                continue
            status_str = status_data.get("status")
            if not status_str:
                continue

            try:
                new_status = ToolStatus(status_str)
            except ValueError:
                logger.warning("Unknown status for %s: %s", tool_id, status_str)
                continue

            if tool.status != new_status:
                tool.status = new_status
                updated += 1
                logger.debug("Updated %s status to %s", tool_id, new_status)

        return updated

    def get_tools_by_category(self, category: str) -> list[RegisteredTool]:
        """Get all tools in a specific category."""
        return [t for t in self._tools.values() if t.config.category == category]

    def get_tool_for_ai(self, tool_id: str) -> dict[str, Any] | None:
        """Get tool information formatted for AI agents."""
        tool = self.get_tool(tool_id)
        if not tool or not tool.is_available:
            return None
        return self._tool_to_ai_dict(tool)

    def list_tools_for_ai(self) -> list[dict[str, Any]]:
        """Get all available tools formatted for AI agents."""
        return [
            self._tool_to_ai_dict(t) for t in self._tools.values() if t.is_available
        ]

    def _tool_to_ai_dict(self, tool: RegisteredTool) -> dict[str, Any]:
        """Convert a RegisteredTool to a dict for AI consumption."""
        config = tool.config
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "category": config.category,
            "command": config.execution.command,
            "args_template": config.execution.args_template,
            "capabilities": config.metadata.capabilities,
            "risk_level": config.metadata.risk_level,
            "summary": config.get_ai_summary(),
        }

    # --- Plugin Management ---

    async def add_plugin(self, data: dict[str, Any]) -> RegisteredTool:
        """Add a new plugin from uploaded data."""
        # Config is returned by validator
        config = self.validator.validate_plugin(data)

        if config.id in self._tools:
            existing = self._tools[config.id]
            if existing.config.is_system:
                raise PluginValidationError(
                    f"Cannot overwrite system tool: {config.id}"
                )
            existing.config = config
            existing.status = ToolStatus.PENDING
        else:
            self._tools[config.id] = RegisteredTool(
                config=config,
                status=ToolStatus.PENDING,
            )

        # Save to disk
        await self._save_plugin(config)

        return self._tools[config.id]

    async def _save_plugin(self, config: ToolConfig) -> None:
        """Save a plugin configuration to disk."""
        # Validate ID for filesystem safety
        if not re.match(r"^[a-zA-Z0-9_-]+$", config.id):
            raise ValueError(f"Invalid tool ID for filesystem: {config.id}")

        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        temp_path = self.plugins_dir / f".{config.id}.json.tmp"
        target_path = self.plugins_dir / f"{config.id}.json"

        try:
            data = config.model_dump()
            async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2))
                await f.write("\n")
            temp_path.rename(target_path)
        except (OSError, TypeError, ValueError) as e:
            if temp_path.exists():
                temp_path.unlink()
            raise OSError(f"Failed to save plugin {config.id}: {e}") from e

    async def remove_plugin(self, tool_id: str) -> bool:
        """Remove a plugin from the registry."""
        # Delegate logic (mostly handled here in original, keeping it simple)
        if not tool_id or not re.match(r"^[a-zA-Z0-9_-]+$", tool_id):
            logger.warning("Invalid tool ID format for removal: %s", tool_id)
            return False

        if tool_id not in self._tools:
            return False

        tool = self._tools[tool_id]
        if tool.config.is_system:
            logger.warning("Attempted to remove system tool: %s", tool_id)
            return False

        del self._tools[tool_id]

        path = self.plugins_dir / f"{tool_id}.json"
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError as e:
            logger.warning("Failed to remove plugin file %s: %s", path, e)

        return True


# --- Singleton Accessor ---

_registry_instance: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global ToolRegistry instance."""
    global _registry_instance
    if _registry_instance is None:
        # Defaults used here
        _registry_instance = ToolRegistry()
    return _registry_instance


async def initialize_registry(
    plugins_dir: str | Path = "plugins",
    public_key_path: str | Path | None = None,
    safe_mode: bool = True,
) -> ToolRegistry:
    """Initialize the global ToolRegistry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ToolRegistry(
            plugins_dir=plugins_dir,
            public_key_path=public_key_path,
            safe_mode=safe_mode,
        )
        await _registry_instance.load_plugins()
    return _registry_instance
