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
    # Adapter
    "CommandToolAdapter",
    "PluginInstallationError",
    "PluginSignatureError",
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
