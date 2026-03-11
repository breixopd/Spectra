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
    installed_version: str | None
    error_message: str | None
    execution_command: str
    args_template: str
    timeout: int
    icon: str
    color: str


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
