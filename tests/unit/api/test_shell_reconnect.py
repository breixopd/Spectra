"""Tests for shell exploit reconnect authorization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_user(user_id: str = "user-1", *, is_superuser: bool = False):
    user = MagicMock()
    user.id = user_id
    user.username = "tester"
    user.is_superuser = is_superuser
    return user


@pytest.mark.asyncio
class TestReconnectExploitAuthorization:
    async def test_reconnect_denies_finding_with_null_user_id(self):
        from spectra_api.api.routers.shell import reconnect_exploit

        finding = MagicMock()
        finding.user_id = None
        finding.target_id = "target-1"
        finding.tool_source = "exploit"

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=finding))
        )
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        request = MagicMock()
        user = _make_user("user-1")

        with (
            patch("spectra_api.api.routers.shell.async_session_maker", return_value=session),
            patch(
                "spectra_api.api.routers.shell.check_feature_allowed",
                new=AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await reconnect_exploit(request, "finding-1", user)

        assert exc_info.value.status_code == 403

    async def test_reconnect_allows_owner(self):
        from spectra_api.api.routers.shell import reconnect_exploit

        finding = MagicMock()
        finding.user_id = "user-1"
        finding.target_id = "target-1"
        finding.tool_source = "exploit"

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=finding))
        )
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        request = MagicMock()
        user = _make_user("user-1")

        with (
            patch("spectra_api.api.routers.shell.async_session_maker", return_value=session),
            patch(
                "spectra_api.api.routers.shell.check_feature_allowed",
                new=AsyncMock(),
            ),
            patch("spectra_api.api.routers.shell.audit_log_event", new=AsyncMock()),
        ):
            result = await reconnect_exploit(request, "finding-1", user)

        assert result["status"] == "triggered"
        assert result["target"] == "target-1"
