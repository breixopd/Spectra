"""Unit tests verifying schema modules: imports and validation."""

import pytest
from pydantic import ValidationError


class TestDirectModuleImports:
    """Schemas importable from their domain modules."""

    def test_auth_module(self):
        from app.api.schemas.auth import Token, TokenData, UserBase, UserCreate, UserResponse

        assert all(cls is not None for cls in (Token, TokenData, UserBase, UserCreate, UserResponse))

    def test_common_module(self):
        from app.api.schemas.common import PaginatedResponse

        assert PaginatedResponse is not None

    def test_finding_module(self):
        from app.api.schemas.finding import FindingResponse

        assert FindingResponse is not None

    def test_mission_module(self):
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

        for cls in (
            ActionApprovalResponse,
            MissionDeleteResponse,
            MissionDetailResponse,
            MissionFindingSummary,
            MissionResponse,
            StartMissionRequest,
            TargetCreate,
            TargetResponse,
            TargetUpdate,
        ):
            assert cls is not None

    def test_system_module(self):
        from app.api.schemas.system import (
            AdminUserCreate,
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

        for cls in (
            AdminUserCreate,
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
        ):
            assert cls is not None

    def test_tool_module(self):
        from app.api.schemas.tool import (
            InstallToolRequest,
            InstallToolResponse,
            PluginUploadResponse,
            ToolAdminResponse,
            ToolDetailResponse,
            ToolListResponse,
            ToolSummary,
        )

        for cls in (
            InstallToolRequest,
            InstallToolResponse,
            PluginUploadResponse,
            ToolAdminResponse,
            ToolDetailResponse,
            ToolListResponse,
            ToolSummary,
        ):
            assert cls is not None


class TestSchemaValidation:
    """Schema validation with valid and invalid data."""

    def test_token_valid(self):
        from app.api.schemas.auth import Token

        t = Token(access_token="abc123")
        assert t.access_token == "abc123"
        assert t.token_type == "bearer"

    def test_user_create_valid(self):
        from app.api.schemas.auth import UserCreate

        u = UserCreate(username="testuser", email="test@example.com", password="Secret1x")
        assert u.username == "testuser"

    def test_user_create_weak_password_rejected(self):
        from app.api.schemas.auth import UserCreate

        with pytest.raises(ValidationError):
            UserCreate(username="testuser", email="test@example.com", password="weak")

    def test_user_create_no_uppercase_rejected(self):
        from app.api.schemas.auth import UserCreate

        with pytest.raises(ValidationError):
            UserCreate(username="testuser", email="test@example.com", password="alllower1")

    def test_user_create_invalid_email_rejected(self):
        from app.api.schemas.auth import UserCreate

        with pytest.raises(ValidationError):
            UserCreate(username="testuser", email="not-an-email", password="Secret1x")

    def test_target_create_valid(self):
        from app.api.schemas.mission import TargetCreate

        t = TargetCreate(address="192.168.1.1")
        assert t.address == "192.168.1.1"

    def test_target_create_empty_address_rejected(self):
        from app.api.schemas.mission import TargetCreate

        with pytest.raises(ValidationError):
            TargetCreate(address="")

    def test_start_mission_request_valid(self):
        from app.api.schemas.mission import StartMissionRequest

        m = StartMissionRequest(target="10.0.0.1")
        assert m.target == "10.0.0.1"
        assert m.directive  # has a default

    def test_health_response_valid(self):
        from app.api.schemas.system import HealthResponse

        h = HealthResponse(status="ok", service="api")
        assert h.status == "ok"

    def test_paginated_response_computes_pages(self):
        from app.api.schemas.common import PaginatedResponse

        p = PaginatedResponse(items=[], total=25, page=1, per_page=10)
        assert p.pages == 3  # ceil(25/10)

    def test_paginated_response_single_page(self):
        from app.api.schemas.common import PaginatedResponse

        p = PaginatedResponse(items=["a"], total=1, page=1, per_page=10)
        assert p.pages == 1

    def test_finding_response_valid(self):
        from app.api.schemas.finding import FindingResponse

        f = FindingResponse(
            id="uuid-1",
            title="SQLi",
            description="SQL injection",
            severity="high",
            status="open",
            tool_source="sqlmap",
            created_at="2025-01-01T00:00:00Z",
        )
        assert f.severity == "high"

    def test_install_tool_request_pattern(self):
        from app.api.schemas.tool import InstallToolRequest

        r = InstallToolRequest(tool_id="nmap-scanner")
        assert r.tool_id == "nmap-scanner"

    def test_install_tool_request_invalid_pattern(self):
        from app.api.schemas.tool import InstallToolRequest

        with pytest.raises(ValidationError):
            InstallToolRequest(tool_id="INVALID!")
