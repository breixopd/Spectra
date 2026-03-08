"""Tests for the audit log service."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.audit_log import AuditEventType
from app.services.system.audit import log_event


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_request():
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = "192.168.1.100"
    req.headers = {"user-agent": "Mozilla/5.0 TestAgent"}
    return req


class TestLogEvent:
    @pytest.mark.asyncio
    async def test_creates_audit_log(self, mock_session):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(
                mock_session,
                AuditEventType.LOGIN,
                user_id="user-123",
                details={"ip": "10.0.0.1"},
            )

            repo_inst.create.assert_called_once()
            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["event_type"] == "LOGIN"
            assert call_kwargs["user_id"] == "user-123"
            assert json.loads(call_kwargs["details"]) == {"ip": "10.0.0.1"}
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extracts_ip_from_request(self, mock_session, mock_request):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(
                mock_session,
                AuditEventType.SETTINGS_CHANGED,
                request=mock_request,
            )

            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["ip_address"] == "192.168.1.100"
            assert "Mozilla" in call_kwargs["user_agent"]

    @pytest.mark.asyncio
    async def test_extracts_user_agent_from_request(self, mock_session, mock_request):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(
                mock_session,
                AuditEventType.LOGIN,
                request=mock_request,
            )

            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["user_agent"] == "Mozilla/5.0 TestAgent"

    @pytest.mark.asyncio
    async def test_no_request_sets_none(self, mock_session):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(mock_session, AuditEventType.LOGOUT)

            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["ip_address"] is None
            assert call_kwargs["user_agent"] is None

    @pytest.mark.asyncio
    async def test_request_without_client(self, mock_session):
        req = MagicMock()
        req.client = None
        req.headers = {"user-agent": "Bot/1.0"}

        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(mock_session, AuditEventType.LOGIN, request=req)

            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["ip_address"] is None

    @pytest.mark.asyncio
    async def test_handles_db_error_gracefully(self, mock_session):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock(side_effect=Exception("DB error"))

            # Should not raise
            await log_event(mock_session, AuditEventType.LOGIN, user_id="u1")

            mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_event_types_valid(self, mock_session):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            for evt in AuditEventType:
                await log_event(mock_session, evt, user_id="test")
                call_kwargs = repo_inst.create.call_args[1]
                assert call_kwargs["event_type"] == evt.value

    @pytest.mark.asyncio
    async def test_none_details_stored_as_none(self, mock_session):
        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(mock_session, AuditEventType.LOGOUT, details=None)

            call_kwargs = repo_inst.create.call_args[1]
            assert call_kwargs["details"] is None

    @pytest.mark.asyncio
    async def test_truncates_long_user_agent(self, mock_session):
        req = MagicMock()
        req.client = MagicMock()
        req.client.host = "10.0.0.1"
        req.headers = {"user-agent": "X" * 1000}

        with patch("app.services.system.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.create = AsyncMock()

            await log_event(mock_session, AuditEventType.LOGIN, request=req)

            call_kwargs = repo_inst.create.call_args[1]
            assert len(call_kwargs["user_agent"]) == 512
