"""
Pydantic schemas for API requests and responses.

Provides input validation and serialization for all API endpoints.
All schemas are split into domain modules but re-exported here
for backward compatibility.

Convention:
- Domain schemas live in their own module (finding.py, mission.py, cve.py, etc.).
- Cross-cutting / shared types go in common.py.
- System, admin, health, and configuration schemas (settings, plans, server
  provisioning, AI provider profiles) are grouped in system.py.
"""

from app.api.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    TokenData,
    UserBase,
    UserCreate,
    UserResponse,
)
from app.api.schemas.common import ErrorResponse, PaginatedResponse, StatusResponse
from app.api.schemas.cve import (
    CVEEnrichedResponse,
    CVEExploitsResponse,
    CVELookupResponse,
    SearchExploitResponse,
)
from app.api.schemas.finding import FindingResponse
from app.api.schemas.mission import (
    ActionApprovalResponse,
    MissionDeleteResponse,
    MissionDetailResponse,
    MissionFindingSummary,
    MissionResponse,
    StartMissionRequest,
    TargetCreate,
    TargetResponse,
    TargetUpdate,
)
from app.api.schemas.system import (
    AdminSettingsUpdate,
    AdminUserCreate,
    AdminUserCreateResponse,
    AdminUserUpdate,
    DeleteAccountRequest,
    HealthResponse,
    LLMTestRequest,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    ServerProvisionRequest,
    ServerVerifyRequest,
    SettingsUpdate,
    SystemSetupRequest,
    UserAdminResponse,
)
from app.api.schemas.tool import (
    CommandInfoResponse,
    InstallToolRequest,
    InstallToolResponse,
    PluginSaveResponse,
    PluginUploadResponse,
    TestExecutionResponse,
    ToolDetailResponse,
    ToolExecConfigResponse,
    ToolListResponse,
    ToolMetadataResponse,
    ToolQueueResponse,
    ToolRemoveResponse,
    ToolStatsResponse,
    ToolStealthResponse,
    ToolSummary,
    ToolUIResponse,
    ValidationResponse,
)

__all__ = [
    "ActionApprovalResponse",
    "AdminSettingsUpdate",
    "AdminUserCreate",
    "AdminUserCreateResponse",
    "AdminUserUpdate",
    "DeleteAccountRequest",
    "ErrorResponse",
    "FindingResponse",
    "ForgotPasswordRequest",
    "HealthResponse",
    "InstallToolRequest",
    "InstallToolResponse",
    "LLMTestRequest",
    "MissionDeleteResponse",
    "MissionDetailResponse",
    "MissionFindingSummary",
    "MissionResponse",
    "PaginatedResponse",
    "PlanCreate",
    "PlanResponse",
    "PlanUpdate",
    "PluginUploadResponse",
    "ResetPasswordRequest",
    "ServerProvisionRequest",
    "ServerVerifyRequest",
    "SettingsUpdate",
    "StartMissionRequest",
    "StatusResponse",
    "SystemSetupRequest",
    "TargetCreate",
    "TargetResponse",
    "TargetUpdate",
    "Token",
    "TokenData",
    "ToolDetailResponse",
    "ToolExecConfigResponse",
    "ToolListResponse",
    "ToolMetadataResponse",
    "ToolStatsResponse",
    "ToolStealthResponse",
    "ToolSummary",
    "ToolUIResponse",
    "UserAdminResponse",
    "UserBase",
    "UserCreate",
    "UserResponse",
]
