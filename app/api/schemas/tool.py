"""Tool and plugin schemas."""

from pydantic import BaseModel, Field

from app.services.tools.models import ToolCategory, ToolStatus


class ToolSummary(BaseModel):
    """Summary of a registered tool."""

    id: str
    name: str
    version: str
    category: ToolCategory
    description: str
    status: ToolStatus
    enabled: bool
    icon: str
    color: str


class ToolListResponse(BaseModel):
    """Response for listing tools."""

    tools: list[ToolSummary]
    total: int


class ToolDetailResponse(BaseModel):
    """Detailed information about a tool."""

    id: str
    name: str
    version: str
    category: ToolCategory
    description: str
    status: ToolStatus
    enabled: bool
    installed_version: str | None
    error_message: str | None
    execution_command: str
    args_template: str
    timeout: int
    icon: str
    color: str
    status_message: str | None = None
    status_phase: str | None = None
    last_updated: str | None = None
    install_logs: list[str] = []
    last_output: str | None = None


class PluginUploadResponse(BaseModel):
    """Response after uploading a plugin."""

    success: bool
    tool_id: str
    message: str


class InstallToolRequest(BaseModel):
    """Request to install a tool."""

    tool_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class InstallToolResponse(BaseModel):
    """Response after initiating tool installation."""

    success: bool
    tool_id: str
    status: str
    message: str


class ToolStatsResponse(BaseModel):
    """Execution statistics for a tool."""

    tool_id: str
    total_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_run: str | None = None
    last_duration: float | None = None
    status: str | None = None
    status_message: str | None = None
    last_updated: str | None = None
    install_logs: list[str] = []
    error: str | None = None


class ToolMetadataResponse(BaseModel):
    ai_description: str = ""
    capabilities: list[str] = []
    risk_level: str = "low"
    tags: list[str] = []
    supported_targets: list[str] = []
    use_cases: list[str] = []
    limitations: list[str] = []


class ToolStealthResponse(BaseModel):
    rate_limit: int | None = None
    delay_ms: int | None = None
    extra_args: dict[str, str] = {}


class ToolUIResponse(BaseModel):
    icon: str = ""
    color: str = ""


class ToolExecConfigResponse(BaseModel):
    """Full execution configuration for a tool."""

    id: str
    name: str
    version: str
    category: str
    description: str
    status: str
    command: str
    args_template: str
    timeout: int
    placeholders: list[str]
    args_schema: dict = {}
    arg_modifiers: dict[str, str] = {}
    metadata: ToolMetadataResponse
    stealth: ToolStealthResponse
    parsing_format: str = ""
    ui: ToolUIResponse


class ValidationResponse(BaseModel):
    """Response for plugin validation."""

    valid: bool
    message: str


class PluginSaveResponse(BaseModel):
    """Response after saving an unsigned plugin."""

    status: str
    tool_id: str
    message: str


class ToolQueueResponse(BaseModel):
    """Response for tool installation/queue operations."""

    success: bool
    message: str


class ToolRemoveResponse(BaseModel):
    """Response after removing a tool plugin."""

    success: bool
    message: str


class CommandInfoResponse(BaseModel):
    """Command details in a test execution response."""

    base_command: str
    args_template: str
    timeout_used: int


class TestExecutionResponse(BaseModel):
    """Response for a test tool execution."""

    tool_id: str
    target: str
    success: bool
    exit_code: int = -1
    duration_seconds: float = 0
    stdout: str = ""
    stderr: str = ""
    output_file: str | None = None
    parsed_findings_count: int = 0
    parsed_findings: list[dict] = []
    command_info: CommandInfoResponse
