"""Security tool adapters and wrappers."""

from app.services.tools.adapter import (
    CommandToolAdapter,
    ToolExecutionError,
    create_adapter,
)
from app.services.tools.models import (
    RegisteredTool,
    ToolCategory,
    ToolConfig,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolStatus,
)
from app.services.tools.registry import (
    PluginInstallationError,
    PluginSignatureError,
    PluginValidationError,
    ToolRegistry,
    get_registry,
    initialize_registry,
)

__all__ = [
    # Models
    "ToolCategory",
    "ToolStatus",
    "ToolConfig",
    "RegisteredTool",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    # Registry
    "ToolRegistry",
    "get_registry",
    "initialize_registry",
    "PluginValidationError",
    "PluginSignatureError",
    "PluginInstallationError",
    # Adapter
    "CommandToolAdapter",
    "ToolExecutionError",
    "create_adapter",
]
