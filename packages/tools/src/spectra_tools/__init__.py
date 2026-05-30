"""Security tool adapters and wrappers."""

from spectra_tools.adapter import (
    CommandToolAdapter,
    ToolExecutionError,
    create_adapter,
)
from spectra_tools_core.models import (
    RegisteredTool,
    ToolCategory,
    ToolConfig,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolStatus,
)
from spectra_tools_core.registry import (
    PluginInstallationError,
    PluginValidationError,
    ToolRegistry,
    get_registry,
    initialize_registry,
)

__all__ = [
    # Adapter
    "CommandToolAdapter",
    "PluginInstallationError",
    "PluginValidationError",
    "RegisteredTool",
    # Models
    "ToolCategory",
    "ToolConfig",
    "ToolExecutionError",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    # Registry
    "ToolRegistry",
    "ToolStatus",
    "create_adapter",
    "get_registry",
    "initialize_registry",
]
